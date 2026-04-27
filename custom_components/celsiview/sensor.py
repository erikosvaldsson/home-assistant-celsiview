"""Sensor platform for Celsiview locations."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from homeassistant.components.recorder import get_instance as recorder_get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    get_last_statistics,
)
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

from .api import CELSIVIEW_EPOCH, CelsiviewApiError, Location, Sample
from .bucketing import bucket_hourly
from .const import (
    CONF_BACKFILL_STATES,
    CONF_BASE_URL,
    DEFAULT_BACKFILL_STATES,
    DEFAULT_BASE_URL,
    DOMAIN,
    STYPE_DEVICE_CLASS,
)
from .coordinator import CelsiviewCoordinator
from .state_backfill import StateBackfillUnsupported, async_write_state_rows

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create sensor entities for every selected location."""
    coordinator: CelsiviewCoordinator = hass.data[DOMAIN][entry.entry_id]
    base_url = entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL)

    backfill_states = bool(entry.options.get(CONF_BACKFILL_STATES, DEFAULT_BACKFILL_STATES))

    entities: list[CelsiviewLocationSensor] = []
    for zid in coordinator.selected_zids:
        location = coordinator.data.get(zid) if coordinator.data else None
        entities.append(
            CelsiviewLocationSensor(coordinator, entry, zid, base_url, location, backfill_states)
        )

    async_add_entities(entities)


class CelsiviewLocationSensor(CoordinatorEntity[CelsiviewCoordinator], SensorEntity):
    """One Home Assistant sensor per Celsiview location.

    The sensor serves up to three purposes per poll:

    * its live state / attributes expose the most recent sample the API
      returned on the latest coordinator poll;
    * it walks Celsiview's history endpoint from the last imported
      bucket up to now, aggregates samples into hourly buckets and
      imports them as long-term statistics, so the Statistics dashboard
      and long-zoom history reflect on-device sample times; and
    * if the user has enabled the (advanced, unsupported)
      ``backfill_states`` option, it additionally writes every sample
      directly into the recorder's ``states`` table at its on-device
      timestamp, giving the standard History tab full sample-rate
      detail at the cost of bypassing HA's public API.
    """

    _attr_has_entity_name = False
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: CelsiviewCoordinator,
        entry: ConfigEntry,
        zid: str,
        base_url: str,
        initial: Location | None,
        backfill_states: bool,
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

        # Most-recent hour we've already imported as a statistic. We
        # re-import the latest hour every poll so in-progress hours fill
        # in as more samples arrive.
        self._last_imported_ts: int | None = None
        self._backfill_in_progress = False
        # Direct-to-states backfill is opt-in and bypasses HA's public
        # API; flips off if the recorder rejects us so we don't keep
        # logging the same error every poll.
        self._backfill_states_enabled = backfill_states
        self._last_state_backfilled_ts: int | None = None

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
        self.hass.async_create_task(self._async_backfill_statistics())

    async def async_added_to_hass(self) -> None:
        """Kick off an initial backfill once the entity is live."""
        await super().async_added_to_hass()
        self.hass.async_create_task(self._async_backfill_statistics())

    async def _async_backfill_statistics(self) -> None:
        """Fetch Celsiview samples and import them as long-term statistics."""
        if self._backfill_in_progress:
            return
        if not self.entity_id:  # not yet registered
            return
        loc = self._location
        if loc is None:
            return

        self._backfill_in_progress = True
        try:
            start_ts = await self._determine_start_ts(loc)
            end_ts = int(datetime.now(tz=UTC).timestamp())
            if end_ts <= start_ts:
                return

            try:
                samples = await self.coordinator.client.fetch_history(self._zid, start_ts, end_ts)
            except CelsiviewApiError as err:
                _LOGGER.warning("Celsiview history fetch failed for %s: %s", self.entity_id, err)
                return

            if not samples:
                return

            buckets = bucket_hourly(samples)
            if not buckets:
                return

            metadata: StatisticMetaData = {
                "has_mean": True,
                "has_sum": False,
                "name": loc.name,
                "source": "recorder",
                "statistic_id": self.entity_id,
                "unit_of_measurement": loc.last_unit,
            }
            stats: list[StatisticData] = [
                StatisticData(
                    start=datetime.fromtimestamp(b.start_ts, tz=UTC),
                    mean=b.mean,
                    min=b.minimum,
                    max=b.maximum,
                )
                for b in buckets
            ]
            async_import_statistics(self.hass, metadata, stats)
            self._last_imported_ts = buckets[-1].start_ts
            _LOGGER.debug(
                "Imported %d hourly bucket(s) (%d sample(s)) for %s",
                len(buckets),
                len(samples),
                self.entity_id,
            )

            if self._backfill_states_enabled:
                await self._async_backfill_states(samples)
        finally:
            self._backfill_in_progress = False

    async def _async_backfill_states(self, samples: list[Sample]) -> None:
        """Write fetched samples directly into the recorder's states table.

        Opt-in path enabled via the ``backfill_states`` option. We rely
        on a per-entity cursor so we don't re-process samples we've
        already inserted, and the writer itself dedupes against the DB
        as a second line of defence.
        """
        cursor = self._last_state_backfilled_ts
        new_samples = [s for s in samples if cursor is None or s.ts > cursor]
        if not new_samples:
            return
        try:
            inserted = await async_write_state_rows(self.hass, self.entity_id, new_samples)
        except StateBackfillUnsupported as err:
            _LOGGER.error(
                "Disabling state backfill for %s — recorder schema check failed: %s",
                self.entity_id,
                err,
            )
            self._backfill_states_enabled = False
            return
        except Exception:
            _LOGGER.exception(
                "Direct state backfill failed for %s; disabling for this session",
                self.entity_id,
            )
            self._backfill_states_enabled = False
            return

        self._last_state_backfilled_ts = max(s.ts for s in new_samples)
        if inserted:
            _LOGGER.debug(
                "Wrote %d historical state row(s) directly to recorder for %s",
                inserted,
                self.entity_id,
            )

    async def _determine_start_ts(self, loc: Location) -> int:
        """Return the timestamp to resume fetching history from.

        On first run we ask the recorder for the latest imported
        statistic; if none exists we back-fill from the location's
        ``valid_start``. Subsequent runs re-use the in-memory cursor to
        avoid hitting the recorder on every poll, but still overlap the
        latest hour so partial buckets get filled in.
        """
        if self._last_imported_ts is not None:
            # Re-fetch the latest bucket so it fills in as more samples
            # come in within the same hour.
            return max(self._last_imported_ts, CELSIVIEW_EPOCH)

        recorder = recorder_get_instance(self.hass)
        last = await recorder.async_add_executor_job(
            get_last_statistics,
            self.hass,
            1,
            self.entity_id,
            True,
            {"mean"},
        )
        entries = last.get(self.entity_id) or []
        if entries:
            last_start = entries[0].get("start")
            if isinstance(last_start, datetime):
                return int(last_start.timestamp())
            if isinstance(last_start, int | float):
                return int(last_start)

        if loc.valid_start and loc.valid_start > 0:
            return loc.valid_start
        return CELSIVIEW_EPOCH

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
