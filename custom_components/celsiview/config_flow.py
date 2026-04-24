"""Config and options flow for the Celsiview integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    CelsiviewApiError,
    CelsiviewAuthError,
    CelsiviewClient,
    Location,
)
from .const import (
    CONF_APPLICATION_KEY,
    CONF_BASE_URL,
    CONF_CLIENT_SECRET,
    CONF_SCAN_INTERVAL_MINUTES,
    CONF_SELECTED_LOCATIONS,
    DEFAULT_BASE_URL,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    MAX_SCAN_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
)

_LOGGER = logging.getLogger(__name__)


def _credentials_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_BASE_URL,
                default=defaults.get(CONF_BASE_URL, DEFAULT_BASE_URL),
            ): str,
            vol.Required(
                CONF_APPLICATION_KEY,
                default=defaults.get(CONF_APPLICATION_KEY, ""),
            ): str,
            vol.Optional(
                CONF_CLIENT_SECRET,
                default=defaults.get(CONF_CLIENT_SECRET, ""),
            ): str,
            vol.Required(
                CONF_SCAN_INTERVAL_MINUTES,
                default=defaults.get(
                    CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES
                ),
            ): vol.All(
                vol.Coerce(int),
                vol.Range(min=MIN_SCAN_INTERVAL_MINUTES, max=MAX_SCAN_INTERVAL_MINUTES),
            ),
        }
    )


def _selection_schema(
    locations: list[Location],
    selected: list[str],
) -> vol.Schema:
    options = [
        selector.SelectOptionDict(
            value=loc.zid,
            label=_label_for(loc),
        )
        for loc in sorted(locations, key=lambda loc: loc.name.lower())
    ]
    return vol.Schema(
        {
            vol.Required(CONF_SELECTED_LOCATIONS, default=selected): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                    custom_value=False,
                )
            ),
        }
    )


def _label_for(loc: Location) -> str:
    bits: list[str] = [loc.name]
    if loc.last_stype:
        bits.append(f"[{loc.last_stype}]")
    if loc.last_unit:
        bits.append(loc.last_unit)
    return " ".join(bits)


async def _verify_and_list(
    hass,
    data: dict[str, Any],
) -> list[Location]:
    session = async_get_clientsession(hass)
    client = CelsiviewClient(
        session=session,
        base_url=data[CONF_BASE_URL],
        application_key=data[CONF_APPLICATION_KEY],
        client_secret=data.get(CONF_CLIENT_SECRET) or None,
    )
    return await client.list_locations()


class CelsiviewConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._credentials: dict[str, Any] = {}
        self._locations: list[Location] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """First step: collect credentials and poll interval."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_BASE_URL] = user_input[CONF_BASE_URL].rstrip("/")
            await self.async_set_unique_id(
                f"{user_input[CONF_BASE_URL]}::{user_input[CONF_APPLICATION_KEY]}"
            )
            self._abort_if_unique_id_configured()

            try:
                self._locations = await _verify_and_list(self.hass, user_input)
            except CelsiviewAuthError:
                errors["base"] = "invalid_auth"
            except CelsiviewApiError as err:
                _LOGGER.warning("Celsiview connection error: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during Celsiview setup")
                errors["base"] = "unknown"

            if not errors:
                self._credentials = user_input
                return await self.async_step_select()

        return self.async_show_form(
            step_id="user",
            data_schema=_credentials_schema(user_input),
            errors=errors,
        )

    async def async_step_select(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Second step: pick which locations to import as sensors."""
        if not self._locations:
            return self.async_abort(reason="no_locations")

        if user_input is not None:
            data = dict(self._credentials)
            options = {
                CONF_SELECTED_LOCATIONS: user_input[CONF_SELECTED_LOCATIONS],
                CONF_SCAN_INTERVAL_MINUTES: self._credentials[
                    CONF_SCAN_INTERVAL_MINUTES
                ],
            }
            return self.async_create_entry(
                title=_title_for(self._credentials),
                data=data,
                options=options,
            )

        return self.async_show_form(
            step_id="select",
            data_schema=_selection_schema(self._locations, []),
            description_placeholders={"count": str(len(self._locations))},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return CelsiviewOptionsFlow(entry)


class CelsiviewOptionsFlow(config_entries.OptionsFlow):
    """Allow the user to change poll interval and sensor selection."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry
        self._locations: list[Location] = []

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        try:
            self._locations = await _verify_and_list(self.hass, dict(self._entry.data))
        except CelsiviewAuthError:
            errors["base"] = "invalid_auth"
        except CelsiviewApiError as err:
            _LOGGER.warning("Celsiview connection error: %s", err)
            errors["base"] = "cannot_connect"

        if errors:
            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema({}),
                errors=errors,
            )

        current_selected = list(
            self._entry.options.get(
                CONF_SELECTED_LOCATIONS,
                self._entry.data.get(CONF_SELECTED_LOCATIONS, []),
            )
        )
        current_interval = int(
            self._entry.options.get(
                CONF_SCAN_INTERVAL_MINUTES,
                self._entry.data.get(
                    CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES
                ),
            )
        )

        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    CONF_SELECTED_LOCATIONS: user_input[CONF_SELECTED_LOCATIONS],
                    CONF_SCAN_INTERVAL_MINUTES: user_input[CONF_SCAN_INTERVAL_MINUTES],
                },
            )

        schema = _selection_schema(self._locations, current_selected).extend(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL_MINUTES, default=current_interval
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(
                        min=MIN_SCAN_INTERVAL_MINUTES, max=MAX_SCAN_INTERVAL_MINUTES
                    ),
                ),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={"count": str(len(self._locations))},
        )


def _title_for(data: dict[str, Any]) -> str:
    host = data.get(CONF_BASE_URL, DEFAULT_BASE_URL)
    return host.replace("https://", "").replace("http://", "").rstrip("/")
