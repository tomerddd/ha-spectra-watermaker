"""The Spectra Watermaker Assistant integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.NUMBER,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Spectra Watermaker Assistant from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # TODO: Initialize the coordinator here
    # coordinator = SprectraWatermakerCoordinator(hass, entry)
    # await coordinator.async_start()
    # hass.data[DOMAIN][entry.entry_id] = coordinator

    hass.data[DOMAIN][entry.entry_id] = {}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # TODO: Stop coordinator WebSocket connections
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
