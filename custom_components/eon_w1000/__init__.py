"""E.ON W1000 smart meter data via scheduled e-mail exports."""

from __future__ import annotations

from pathlib import Path

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import EonCoordinator
from .parser import ParseError

PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_IMPORT_FILE = "import_file"
SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("path"): cv.string,
        vol.Optional("config_entry_id"): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the manual file import service."""

    async def import_file(call: ServiceCall) -> ServiceResponse:
        entries = [
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.state is ConfigEntryState.LOADED
        ]
        entry_id = call.data.get("config_entry_id")
        if entry_id:
            entries = [entry for entry in entries if entry.entry_id == entry_id]
        if len(entries) != 1:
            raise ServiceValidationError(
                "Specify config_entry_id: found "
                f"{len(entries)} matching loaded E.ON W1000 entries"
            )
        coordinator: EonCoordinator = entries[0].runtime_data

        path = call.data["path"]
        if not hass.config.is_allowed_path(path):
            raise ServiceValidationError(
                f"'{path}' is not in an allowed directory (see allowlist_external_dirs)"
            )
        try:
            data = await hass.async_add_executor_job(Path(path).read_bytes)
            parsed = await hass.async_add_executor_job(coordinator.parse, data)
        except OSError as err:
            raise HomeAssistantError(f"Cannot read '{path}': {err}") from err
        except ParseError as err:
            raise HomeAssistantError(f"Cannot interpret '{path}': {err}") from err

        written = await coordinator.async_import_parsed(parsed)
        await coordinator.async_refresh_public_data()
        return {
            "layout": parsed.layout,
            "pod": parsed.pod,
            "pods_in_file": parsed.pods,
            "variables": parsed.variables,
            "resolution_minutes": parsed.step.total_seconds() / 60,
            "imported": {
                kind: {
                    "hours": len(hourly),
                    "first": min(hourly).isoformat(),
                    "last": max(hourly).isoformat(),
                    "kwh": round(sum(hourly.values()), 3),
                }
                for kind, hourly in written.items()
            },
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_FILE,
        import_file,
        schema=SERVICE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = EonCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Forget the e-mail cursor; imported statistics are kept."""
    await EonCoordinator(hass, entry).async_remove_store()
