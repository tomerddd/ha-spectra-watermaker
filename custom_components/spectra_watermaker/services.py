"""Service registration for Spectra Watermaker."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import SpectraCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_START = "start"
SERVICE_STOP = "stop"
SERVICE_FLUSH = "flush"
SERVICE_GET_RUN_HISTORY = "get_run_history"

SERVICE_START_SCHEMA = vol.Schema(
    {
        vol.Optional("duration_hours"): vol.All(
            vol.Coerce(float), vol.Range(min=0.5, max=8.0)
        ),
    }
)

SERVICE_STOP_SCHEMA = vol.Schema({})

SERVICE_FLUSH_SCHEMA = vol.Schema({})

SERVICE_GET_RUN_HISTORY_SCHEMA = vol.Schema(
    {
        vol.Optional("limit", default=10): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=50)
        ),
    }
)


def _get_coordinator(hass: HomeAssistant) -> SpectraCoordinator | None:
    """Get the first available coordinator."""
    domain_data = hass.data.get(DOMAIN, {})
    for coordinator in domain_data.values():
        if isinstance(coordinator, SpectraCoordinator):
            return coordinator
    return None


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for Spectra Watermaker."""

    async def handle_start(call: ServiceCall) -> None:
        """Handle the start service call."""
        coordinator = _get_coordinator(hass)
        if not coordinator:
            _LOGGER.error("No Spectra Watermaker coordinator found")
            return
        duration = call.data.get("duration_hours")
        await coordinator.async_start_watermaker(duration)

    async def handle_stop(call: ServiceCall) -> None:
        """Handle the stop service call."""
        coordinator = _get_coordinator(hass)
        if not coordinator:
            _LOGGER.error("No Spectra Watermaker coordinator found")
            return
        await coordinator.async_stop_watermaker()

    async def handle_flush(call: ServiceCall) -> None:
        """Handle the flush service call."""
        coordinator = _get_coordinator(hass)
        if not coordinator:
            _LOGGER.error("No Spectra Watermaker coordinator found")
            return
        await coordinator.async_flush()

    async def handle_get_run_history(call: ServiceCall) -> ServiceResponse:
        """Handle the get_run_history service call."""
        coordinator = _get_coordinator(hass)
        if not coordinator:
            _LOGGER.error("No Spectra Watermaker coordinator found")
            return {"runs": []}
        limit = call.data.get("limit", 10)
        runs = coordinator.history.get_history(limit)
        return {"runs": runs}

    hass.services.async_register(
        DOMAIN, SERVICE_START, handle_start, schema=SERVICE_START_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_STOP, handle_stop, schema=SERVICE_STOP_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_FLUSH, handle_flush, schema=SERVICE_FLUSH_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_RUN_HISTORY,
        handle_get_run_history,
        schema=SERVICE_GET_RUN_HISTORY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload Spectra Watermaker services."""
    hass.services.async_remove(DOMAIN, SERVICE_START)
    hass.services.async_remove(DOMAIN, SERVICE_STOP)
    hass.services.async_remove(DOMAIN, SERVICE_FLUSH)
    hass.services.async_remove(DOMAIN, SERVICE_GET_RUN_HISTORY)
