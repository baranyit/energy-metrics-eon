"""Diagnostic sensors showing how fresh the imported data is."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, KIND_EXPORT, KIND_IMPORT
from .coordinator import EonCoordinator

KEYS = ("last_email", "next_check", f"last_data_{KIND_IMPORT}", f"last_data_{KIND_EXPORT}")


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: EonCoordinator = entry.runtime_data
    async_add_entities(EonTimestampSensor(coordinator, entry, key) for key in KEYS)


class EonTimestampSensor(CoordinatorEntity[EonCoordinator], SensorEntity):
    """Last processed e-mail, next e-mail check or newest imported hour."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: EonCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="E.ON",
            model="W1000",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> datetime | None:
        data = self.coordinator.data or {}
        if self._key in ("last_email", "next_check"):
            return data.get(self._key)
        kind = self._key.removeprefix("last_data_")
        return data.get("last_data", {}).get(kind)
