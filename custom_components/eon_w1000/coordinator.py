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
from .parser import ParsedExport, ParseError, parse_export
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

    async def _load_state(self) -> dict:
        if self._state is None:
            self._state = await self._store.async_load() or {}
            self._state.setdefault("cursor", 0)
            self._state.setdefault("seen", [])
            self._state.setdefault("last_email", None)
            self._state.setdefault("last_data", {})
            # kind -> UTC day -> {"step": minutes, "v": [kWh per interval]}
            self._state.setdefault("intervals", {})
        return self._state

    async def async_import_parsed(self, parsed: ParsedExport) -> dict[str, dict[datetime, float]]:
        """Merge a parsed file into the stored intervals and update statistics.

        Values are merged per interval (e.g. 15 minutes): a value for an
        interval replaces the stored one, and intervals missing from the file
        keep their stored value. The affected hours are then recomputed from
        the merged intervals, so re-sent data is never added up and an
        incomplete file never lowers an hour that was already complete.
        Returns the hourly values written, per kind.
        """
        state = await self._load_state()
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
            "last_email": dt_util.parse_datetime(state["last_email"])
            if state["last_email"]
            else None,
            "last_data": {
                kind: dt_util.parse_datetime(value)
                for kind, value in state["last_data"].items()
            },
        }

    async def _async_update_data(self) -> dict:
        state = await self._load_state()

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
                for attachment in message.attachments:
                    if not attachment.name.lower().endswith(DATA_EXTENSIONS):
                        continue
                    try:
                        parsed = await self.hass.async_add_executor_job(
                            self.parse, attachment.data
                        )
                    except ParseError as err:
                        # Stop here without advancing, so the e-mail is retried
                        # once the configuration (or the parser) is fixed.
                        raise UpdateFailed(
                            f"Cannot read '{attachment.name}' from the e-mail "
                            f"'{message.subject}': {err}"
                        ) from err
                    await self.async_import_parsed(parsed)

                state["cursor"] = max(state["cursor"], message.date_ms)
                state["seen"] = [*state["seen"], message.id][-SEEN_IDS_KEPT:]
                state["last_email"] = dt_util.utc_from_timestamp(
                    state["cursor"] / 1000
                ).isoformat()
                await self._store.async_save(state)

            if messages:  # already seen ones still move the cursor
                state["cursor"] = max(state["cursor"], *(m.date_ms for m in messages))
                await self._store.async_save(state)

            if len(messages) < PAGE_LIMIT:
                break

        return self._public_data(state)

    async def async_refresh_public_data(self) -> None:
        """Push stored state to entities after a manual file import."""
        self.async_set_updated_data(self._public_data(await self._load_state()))

    async def async_remove_store(self) -> None:
        await self._store.async_remove()
