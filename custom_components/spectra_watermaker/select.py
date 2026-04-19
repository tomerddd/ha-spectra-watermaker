"""Select platform for Spectra Watermaker Assistant."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, DEFAULT_MODEL
from .coordinator import SpectraCoordinator
from .models import WaterDestination, WatermakerState


class SpectraWaterDestinationSelect(SelectEntity):
    """Water destination select entity (tank/overboard)."""

    _attr_has_entity_name = True
    _attr_translation_key = "water_destination"
    _attr_icon = "mdi:water-outline"
    _attr_options = [WaterDestination.TANK.value, WaterDestination.OVERBOARD.value]

    def __init__(self, coordinator: SpectraCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_water_destination_select"
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.config_entry.entry_id)},
            "name": "Watermaker",
            "manufacturer": MANUFACTURER,
            "model": coordinator.sensor_data.device or DEFAULT_MODEL,
        }

    @property
    def current_option(self) -> str | None:
        """Return the current water destination."""
        if not self._coordinator.is_running:
            return None
        return self._coordinator.water_destination.value

    @property
    def available(self) -> bool:
        """Only available while running."""
        return self._coordinator.state == WatermakerState.RUNNING

    async def async_select_option(self, option: str) -> None:
        """Change the water destination."""
        current = self._coordinator.water_destination.value
        if option != current:
            await self._coordinator.async_toggle_destination()

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
    """Set up Spectra Watermaker select entities from a config entry."""
    coordinator: SpectraCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SpectraWaterDestinationSelect(coordinator)])
