"""Constants for the Celsiview integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "celsiview"

DEFAULT_BASE_URL = "https://api.celsiview.se"
# The Celsiview web app lives at app.celsiview.se and has its own
# /api/v2/... endpoints that behave differently (e.g. location lists are
# filtered for UI rendering). Existing config entries pointing at the
# app host are migrated to the API host on setup.
LEGACY_APP_HOSTS = ("https://app.celsiview.se", "http://app.celsiview.se")

DEFAULT_SCAN_INTERVAL_MINUTES = 15
MIN_SCAN_INTERVAL_MINUTES = 1
MAX_SCAN_INTERVAL_MINUTES = 24 * 60

CONF_BASE_URL = "base_url"
CONF_APPLICATION_KEY = "application_key"
CONF_CLIENT_SECRET = "client_secret"
CONF_SCAN_INTERVAL_MINUTES = "scan_interval_minutes"
CONF_SELECTED_LOCATIONS = "selected_locations"
CONF_BACKFILL_STATES = "backfill_states"

DEFAULT_BACKFILL_STATES = False

# Highest recorder schema version this integration has been tested
# against for the direct-DB state backfill. If HA's recorder is newer we
# still try, but log a warning so users know they're past the tested
# range. If older we refuse, since the column layout differs.
RECORDER_SCHEMA_VERSION_MIN = 48
RECORDER_SCHEMA_VERSION_TESTED = 53

DEFAULT_SCAN_INTERVAL = timedelta(minutes=DEFAULT_SCAN_INTERVAL_MINUTES)

# Mapping from Celsiview sensor type codes (`stype`) to Home Assistant
# device classes. Only the most common ones are mapped; anything unknown
# becomes a plain numeric sensor with the unit reported by the API.
STYPE_DEVICE_CLASS: dict[str, str] = {
    "T": "temperature",
    "THP": "temperature",
    "TLP": "temperature",
    "H": "humidity",
    "RH": "humidity",
    "HHP": "humidity",
    "HLP": "humidity",
    "P": "pressure",
    "HP": "pressure",
    "CO2": "carbon_dioxide",
    "CO": "carbon_monoxide",
    "LX": "illuminance",
    "LUX": "illuminance",
    "V": "voltage",
    "A": "current",
    "W": "power",
    "KWH": "energy",
    "DB": "sound_pressure",
    "PA": "pressure",
    "MPA": "pressure",
    "BAR": "pressure",
}
