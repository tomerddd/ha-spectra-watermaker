"""Switch platform for Spectra Watermaker Assistant."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_POWER_SWITCH, DOMAIN, MANUFACTURER, DEFAULT_MODEL
from .coordinator import SpectraCoordinator
from .models import WatermakerState


class SpectraPowerSwitch(SwitchEntity):
    """Power switch entity for Spectra Watermaker.

    Controls the configured outlet switch entity.
    Blocks power-off during flush.
    Only created if a power outlet switch is configured.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "power"
    _attr_icon = "mdi:power-plug"

    def __init__(self, coordinator: SpectraCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_power"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.config_entry.entry_id)},
            "name": "Watermaker",
            "manufacturer": MANUFACTURER,
            "model": coordinator.sensor_data.device or DEFAULT_MODEL,
        }

    @property
    def is_on(self) -> bool:
        """Return true if the switch is on."""
        return self._coordinator.state != WatermakerState.OFF

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return True

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on the watermaker power."""
        await self._coordinator.async_power_on()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off the watermaker power.

        Blocks during flush to protect membranes.
        """
        if self._coordinator.state == WatermakerState.FLUSHING:
            # Don't cut power during flush
            return
        await self._coordinator.async_power_off()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_coordinator_update)
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Spectra Watermaker switch from a config entry."""
    # Only create power switch if outlet is configured
    if not entry.data.get(CONF_POWER_SWITCH):
        return

    coordinator: SpectraCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SpectraPowerSwitch(coordinator)])
