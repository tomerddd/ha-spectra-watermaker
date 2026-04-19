"""Config flow for Spectra Watermaker Assistant."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import websockets.exceptions

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AUTO_OFF_DELAY,
    CONF_HOST,
    CONF_POWER_SENSOR,
    CONF_POWER_SWITCH,
    CONF_TANK_FULL_THRESHOLD,
    CONF_TANK_SENSOR_PORT,
    CONF_TANK_SENSOR_STBD,
    DEFAULT_AUTO_OFF_MINUTES,
    DEFAULT_TANK_FULL_THRESHOLD,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class SpectraWatermakerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Spectra Watermaker Assistant."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._host: str = ""
        self._device_name: str = "Watermaker"

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow handler."""
        return SpectraWatermakerOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: Watermaker IP address."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]

            # Prevent duplicate entries for same host
            self._async_abort_entries_match({CONF_HOST: host})

            # Validate: try to connect to WebSocket
            try:
                import websockets

                uri = f"ws://{host}:9001"
                async with websockets.connect(
                    uri,
                    subprotocols=["dumb-increment-protocol"],
                    open_timeout=5,
                ) as ws:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5)
                    data = json.loads(msg)
                    self._device_name = data.get("device", "Spectra Watermaker")
            except (
                OSError,
                asyncio.TimeoutError,
                ValueError,
                json.JSONDecodeError,
                websockets.exceptions.WebSocketException,
            ):
                _LOGGER.exception("Failed to connect to Spectra at %s", host)
                errors["base"] = "cannot_connect"
            else:
                # Store host and device name, move to options step
                self._host = host
                return await self.async_step_options()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                }
            ),
            errors=errors,
        )

    async def async_step_options(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: Optional power outlet and tank sensors."""
        if user_input is not None:
            # Merge with host from step 1
            data = {
                CONF_HOST: self._host,
                CONF_POWER_SWITCH: user_input.get(CONF_POWER_SWITCH),
                CONF_POWER_SENSOR: user_input.get(CONF_POWER_SENSOR),
                CONF_TANK_SENSOR_PORT: user_input.get(CONF_TANK_SENSOR_PORT),
                CONF_TANK_SENSOR_STBD: user_input.get(CONF_TANK_SENSOR_STBD),
                CONF_TANK_FULL_THRESHOLD: user_input.get(
                    CONF_TANK_FULL_THRESHOLD, DEFAULT_TANK_FULL_THRESHOLD
                ),
            }

            return self.async_create_entry(
                title=f"Spectra {self._device_name}",
                data=data,
            )

        return self.async_show_form(
            step_id="options",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_POWER_SWITCH): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="switch"),
                    ),
                    vol.Optional(CONF_POWER_SENSOR): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain="sensor",
                            device_class="power",
                        ),
                    ),
                    vol.Optional(CONF_TANK_SENSOR_PORT): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="sensor"),
                    ),
                    vol.Optional(CONF_TANK_SENSOR_STBD): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="sensor"),
                    ),
                    vol.Optional(
                        CONF_TANK_FULL_THRESHOLD,
                        default=DEFAULT_TANK_FULL_THRESHOLD,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=50,
                            max=100,
                            step=1,
                            unit_of_measurement="%",
                            mode="slider",
                        ),
                    ),
                }
            ),
        )


class SpectraWatermakerOptionsFlow(OptionsFlow):
    """Handle options flow for Spectra Watermaker."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self._config_entry.options

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_AUTO_OFF_DELAY,
                        default=current.get(
                            CONF_AUTO_OFF_DELAY, DEFAULT_AUTO_OFF_MINUTES
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=60,
                            step=1,
                            unit_of_measurement="min",
                            mode="slider",
                        ),
                    ),
                }
            ),
        )
