"""Constants for the Celsiview integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "celsiview"

DEFAULT_BASE_URL = "https://app.celsiview.se"
DEFAULT_SCAN_INTERVAL_MINUTES = 15
MIN_SCAN_INTERVAL_MINUTES = 1
MAX_SCAN_INTERVAL_MINUTES = 24 * 60

CONF_BASE_URL = "base_url"
CONF_APPLICATION_KEY = "application_key"
CONF_CLIENT_SECRET = "client_secret"
CONF_SCAN_INTERVAL_MINUTES = "scan_interval_minutes"
CONF_SELECTED_LOCATIONS = "selected_locations"

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
