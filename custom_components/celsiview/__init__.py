"""The Celsiview integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CelsiviewClient
from .const import (
    CONF_APPLICATION_KEY,
    CONF_BASE_URL,
    CONF_CLIENT_SECRET,
    CONF_SCAN_INTERVAL_MINUTES,
    CONF_SELECTED_LOCATIONS,
    DEFAULT_BASE_URL,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
)
from .coordinator import CelsiviewCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Celsiview from a config entry."""
    session = async_get_clientsession(hass)
    client = CelsiviewClient(
        session=session,
        base_url=entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
        application_key=entry.data[CONF_APPLICATION_KEY],
        client_secret=entry.data.get(CONF_CLIENT_SECRET) or None,
    )

    scan_interval_minutes = entry.options.get(
        CONF_SCAN_INTERVAL_MINUTES,
        entry.data.get(CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES),
    )
    selected = entry.options.get(
        CONF_SELECTED_LOCATIONS,
        entry.data.get(CONF_SELECTED_LOCATIONS, []),
    )

    coordinator = CelsiviewCoordinator(
        hass,
        client=client,
        selected_zids=list(selected),
        scan_interval=timedelta(minutes=int(scan_interval_minutes)),
        entry_title=entry.title,
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change (selection or poll interval)."""
    await hass.config_entries.async_reload(entry.entry_id)
