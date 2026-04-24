"""Data update coordinator for the Celsiview integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CelsiviewApiError, CelsiviewAuthError, CelsiviewClient, Location
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class CelsiviewCoordinator(DataUpdateCoordinator[dict[str, Location]]):
    """Polls the Celsiview API on a fixed interval."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: CelsiviewClient,
        selected_zids: list[str],
        scan_interval: timedelta,
        entry_title: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({entry_title})",
            update_interval=scan_interval,
        )
        self.client = client
        self.selected_zids = list(selected_zids)

    async def _async_update_data(self) -> dict[str, Location]:
        try:
            return await self.client.get_locations(self.selected_zids)
        except CelsiviewAuthError as err:
            raise UpdateFailed(f"Authentication error: {err}") from err
        except CelsiviewApiError as err:
            raise UpdateFailed(str(err)) from err

    def update_selection(self, selected_zids: list[str]) -> None:
        """Replace the set of locations this coordinator polls."""
        self.selected_zids = list(selected_zids)
