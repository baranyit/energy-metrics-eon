"""Polls the Apps Script bridge and imports new exports."""

from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util, slugify

from .api import BridgeAuthError, BridgeClient, BridgeError
from .const import (
    CONF_EXPORT_COLUMN,
    CONF_IMPORT_COLUMN,
    CONF_INTERVAL_END,
    CONF_POD,
    CONF_SCRIPT_URL,
    CONF_TOKEN,
    DATA_EXTENSIONS,
    DOMAIN,
    KIND_EXPORT,
    KIND_IMPORT,
    KIND_NAMES,
    MAX_PAGES,
    PAGE_LIMIT,
    SEEN_IDS_KEPT,
    UPDATE_INTERVAL,
)
from .merge import hourly_from_intervals, merge_intervals
from .parser import (
    ParsedExport,
    ParseError,
    check_same_pod,
    parse_attachments,
    parse_export,
)
from .schedule import next_check, should_poll
from .statistics import async_import_hourly

_LOGGER = logging.getLogger(__name__)


class EonCoordinator(DataUpdateCoordinator[dict]):
    """Fetches export e-mails and feeds them into statistics."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {entry.title}",
            update_interval=UPDATE_INTERVAL,
            config_entry=entry,
        )
        self._client = BridgeClient(
            async_get_clientsession(hass),
            entry.data[CONF_SCRIPT_URL],
            entry.data[CONF_TOKEN],
        )
        self._store: Store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self._state: dict | None = None
        self._slug = slugify(entry.data.get(CONF_NAME) or entry.title)

    def statistic_id(self, kind: str) -> str:
        return f"{DOMAIN}:{self._slug}_{kind}"

    def _columns(self) -> dict[str, str]:
        data = self.config_entry.data
        columns = {}
        if data.get(CONF_IMPORT_COLUMN):
            columns[KIND_IMPORT] = data[CONF_IMPORT_COLUMN]
        if data.get(CONF_EXPORT_COLUMN):
            columns[KIND_EXPORT] = data[CONF_EXPORT_COLUMN]
        return columns

    def parse(self, data: bytes) -> ParsedExport:
        """Parse a file with this entry's settings (blocking)."""
        return parse_export(
            data,
            self._columns(),
            interval_end=self.config_entry.data.get(CONF_INTERVAL_END, False),
            pod=self.config_entry.data.get(CONF_POD) or None,
        )

    def parse_files(
        self, files: list[tuple[str, bytes]], known_pod: str | None
    ) -> list[ParsedExport]:
        """Parse the data files of one e-mail with this entry's settings (blocking)."""
        return parse_attachments(
            files,
            self._columns(),
            interval_end=self.config_entry.data.get(CONF_INTERVAL_END, False),
            pod=self.config_entry.data.get(CONF_POD) or None,
            known_pod=known_pod,
        )

    async def _load_state(self) -> dict:
        if self._state is None:
            self._state = await self._store.async_load() or {}
            self._state.setdefault("cursor", 0)
            self._state.setdefault("seen", [])
            self._state.setdefault("last_email", None)
            self._state.setdefault("last_data", {})
            # kind -> UTC day -> {"step": minutes, "v": [kWh per interval]}
            self._state.setdefault("intervals", {})
            # True while an e-mail is waiting to be (re)processed after an error
            self._state.setdefault("retry", False)
            # metering point of the imported data, to keep others out of it
            self._state.setdefault("pod", None)
            # imported e-mails the script has not labelled as processed yet
            self._state.setdefault("unmarked", [])
        return self._state

    def _last_email(self, state: dict) -> datetime | None:
        return dt_util.parse_datetime(state["last_email"]) if state["last_email"] else None

    async def async_import_parsed(self, parsed: ParsedExport) -> dict[str, dict[datetime, float]]:
        """Merge a parsed file into the stored intervals and update statistics.

        Values are merged per interval (e.g. 15 minutes): a value for an
        interval replaces the stored one, and intervals missing from the file
        keep their stored value. The affected hours are then recomputed from
        the merged intervals, so re-sent data is never added up and an
        incomplete file never lowers an hour that was already complete.
        Returns the hourly values written, per kind. Raises ParseError if the
        file belongs to another metering point than the data imported so far.
        """
        state = await self._load_state()
        check_same_pod([state["pod"], parsed.pod], self.config_entry.data.get(CONF_POD))
        if parsed.pod:
            state["pod"] = parsed.pod
        written: dict[str, dict[datetime, float]] = {}
        for kind, intervals in parsed.intervals.items():
            if not intervals:
                continue
            days = state["intervals"].setdefault(kind, {})
            touched = merge_intervals(days, intervals, parsed.step)
            hourly = hourly_from_intervals(days, touched)
            if not hourly:
                continue
            name = f"{self.config_entry.title} {KIND_NAMES[kind]}"
            await async_import_hourly(self.hass, self.statistic_id(kind), name, hourly)
            written[kind] = hourly
            newest = max(hourly).isoformat()
            if newest > (state["last_data"].get(kind) or ""):
                state["last_data"][kind] = newest
        await self._store.async_save(state)
        return written

    def _public_data(self, state: dict) -> dict:
        return {
            "last_email": self._last_email(state),
            "next_check": next_check(
                dt_util.utcnow(),
                self._last_email(state),
                state["retry"],
                self.update_interval or UPDATE_INTERVAL,
            ),
            "last_data": {
                kind: dt_util.parse_datetime(value)
                for kind, value in state["last_data"].items()
            },
        }

    async def _async_update_data(self) -> dict:
        state = await self._load_state()

        # The export arrives once a day: skip polling for a while after the
        # newest processed e-mail (see schedule.py).
        if not should_poll(dt_util.utcnow(), self._last_email(state), state["retry"]):
            return self._public_data(state)

        for _ in range(MAX_PAGES):
            try:
                messages = await self._client.fetch(state["cursor"], PAGE_LIMIT)
            except BridgeAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except BridgeError as err:
                raise UpdateFailed(str(err)) from err

            for message in messages:  # oldest first, so newer data wins
                if message.id in state["seen"]:
                    continue
                files = [
                    (attachment.name, attachment.data)
                    for attachment in message.attachments
                    if attachment.name.lower().endswith(DATA_EXTENSIONS)
                ]
                try:
                    exports = await self.hass.async_add_executor_job(
                        self.parse_files, files, state["pod"]
                    )
                    for parsed in exports:  # in order, so later files win
                        await self.async_import_parsed(parsed)
                except ParseError as err:
                    # Stop here without advancing, so the e-mail is retried
                    # (hourly, ignoring the quiet period) once the
                    # configuration or the parser is fixed. Files imported
                    # before the error are simply imported again.
                    state["retry"] = True
                    await self._store.async_save(state)
                    raise UpdateFailed(
                        f"Cannot process the e-mail '{message.subject}': {err}"
                    ) from err

                state["cursor"] = max(state["cursor"], message.date_ms)
                state["seen"] = [*state["seen"], message.id][-SEEN_IDS_KEPT:]
                if exports:
                    # An e-mail without data for this metering point (e.g. the
                    # export of another one) must not start the quiet period,
                    # and is left alone in the mailbox.
                    state["last_email"] = dt_util.utc_from_timestamp(
                        state["cursor"] / 1000
                    ).isoformat()
                    state["unmarked"] = [*state["unmarked"], message.id][-SEEN_IDS_KEPT:]
                await self._store.async_save(state)

            if messages:  # already seen ones still move the cursor
                state["cursor"] = max(state["cursor"], *(m.date_ms for m in messages))
                await self._store.async_save(state)

            if len(messages) < PAGE_LIMIT:
                break

        if state["retry"]:
            state["retry"] = False
            await self._store.async_save(state)
        await self._async_mark_processed(state)
        return self._public_data(state)

    async def _async_mark_processed(self, state: dict) -> None:
        """Have the script label, mark as read and archive the imported e-mails.

        Purely cosmetic for the mailbox, so a failure never fails the import;
        the ids are kept and sent again with the next poll.
        """
        if not state["unmarked"]:
            return
        try:
            marked = await self._client.mark_processed(state["unmarked"], state["cursor"])
        except BridgeError as err:
            _LOGGER.warning("Could not mark the imported e-mails as processed: %s", err)
            return
        if marked is None:
            _LOGGER.debug(
                "The deployed Apps Script cannot mark e-mails as processed; "
                "update it from apps_script/Code.gs to get that"
            )
        state["unmarked"] = []
        await self._store.async_save(state)

    async def async_poll_now(self) -> None:
        """Ask for new e-mails now, ignoring the quiet period."""
        state = await self._load_state()
        state["retry"] = True  # cleared again by a successful poll
        await self.async_refresh()

    async def async_refresh_public_data(self) -> None:
        """Push stored state to entities after a manual file import."""
        self.async_set_updated_data(self._public_data(await self._load_state()))

    async def async_remove_store(self) -> None:
        await self._store.async_remove()
