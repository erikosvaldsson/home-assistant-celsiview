"""Sensor platform for Celsiview locations."""

from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Location
from .const import CONF_BASE_URL, DEFAULT_BASE_URL, DOMAIN, STYPE_DEVICE_CLASS
from .coordinator import CelsiviewCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create sensor entities for every selected location."""
    coordinator: CelsiviewCoordinator = hass.data[DOMAIN][entry.entry_id]
    base_url = entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL)

    entities: list[CelsiviewLocationSensor] = []
    for zid in coordinator.selected_zids:
        location = coordinator.data.get(zid) if coordinator.data else None
        entities.append(CelsiviewLocationSensor(coordinator, entry, zid, base_url, location))

    async_add_entities(entities)


class CelsiviewLocationSensor(CoordinatorEntity[CelsiviewCoordinator], SensorEntity):
    """One Home Assistant sensor per Celsiview location."""

    _attr_has_entity_name = False
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: CelsiviewCoordinator,
        entry: ConfigEntry,
        zid: str,
        base_url: str,
        initial: Location | None,
    ) -> None:
        super().__init__(coordinator)
        self._zid = zid
        self._entry_id = entry.entry_id
        self._base_url = base_url
        self._attr_unique_id = f"{DOMAIN}_{zid}"
        self._attr_name = initial.name if initial else zid

        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._apply_classification(initial)

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Celsiview ({base_url.replace('https://', '').replace('http://', '')})",
            manufacturer="Celsicom",
            configuration_url=base_url,
            entry_type=None,
        )

    @property
    def _location(self) -> Location | None:
        data = self.coordinator.data
        if not data:
            return None
        return data.get(self._zid)

    @property
    def available(self) -> bool:
        return super().available and self._location is not None

    @property
    def native_value(self) -> float | None:
        loc = self._location
        return loc.last_value if loc else None

    @property
    def native_unit_of_measurement(self) -> str | None:
        loc = self._location
        return loc.last_unit if loc else None

    @property
    def extra_state_attributes(self) -> dict[str, str | int | None]:
        loc = self._location
        if not loc:
            return {}
        last_ts = loc.last_value_time
        last_iso = datetime.fromtimestamp(last_ts, tz=UTC).isoformat() if last_ts else None
        return {
            "zid": loc.zid,
            "sensor_type": loc.last_stype,
            "last_value_time": last_ts,
            "last_value_time_iso": last_iso,
            "account_zid": loc.account_zid,
            "group_zid": loc.group_zid,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        loc = self._location
        if loc is not None:
            self._attr_name = loc.name
            self._apply_classification(loc)
        super()._handle_coordinator_update()

    def _apply_classification(self, loc: Location | None) -> None:
        if not loc or not loc.last_stype:
            self._attr_device_class = None
            return
        mapped = STYPE_DEVICE_CLASS.get(loc.last_stype.upper())
        if mapped is None:
            self._attr_device_class = None
            return
        try:
            self._attr_device_class = SensorDeviceClass(mapped)
        except ValueError:
            self._attr_device_class = None
