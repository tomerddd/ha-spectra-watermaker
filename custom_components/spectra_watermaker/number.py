"""Number platform for Spectra Watermaker Assistant."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEFAULT_RUN_DURATION_HOURS,
    DEFAULT_TANK_FULL_THRESHOLD,
    DOMAIN,
    MANUFACTURER,
    DEFAULT_MODEL,
)
from .coordinator import SpectraCoordinator


class SpectraRunDuration(NumberEntity):
    """Number entity for run duration setting."""

    _attr_has_entity_name = True
    _attr_translation_key = "run_duration"
    _attr_icon = "mdi:timer-cog-outline"
    _attr_native_min_value = 0.5
    _attr_native_max_value = 8.0
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = "h"
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: SpectraCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_run_duration"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.config_entry.entry_id)},
            "name": "Watermaker",
            "manufacturer": MANUFACTURER,
            "model": coordinator.sensor_data.device or DEFAULT_MODEL,
        }

    @property
    def native_value(self) -> float:
        """Return the current run duration."""
        return self._coordinator.run_duration

    async def async_set_native_value(self, value: float) -> None:
        """Set the run duration."""
        self._coordinator.run_duration = value
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_coordinator_update)
        )


class SpectraTankFullThreshold(NumberEntity):
    """Number entity for tank full auto-stop threshold."""

    _attr_has_entity_name = True
    _attr_translation_key = "tank_full_threshold"
    _attr_icon = "mdi:gauge-full"
    _attr_native_min_value = 50
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: SpectraCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_tank_full_threshold"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.config_entry.entry_id)},
            "name": "Watermaker",
            "manufacturer": MANUFACTURER,
            "model": coordinator.sensor_data.device or DEFAULT_MODEL,
        }

    @property
    def native_value(self) -> float:
        """Return the current threshold."""
        return self._coordinator.tank_full_threshold

    async def async_set_native_value(self, value: float) -> None:
        """Set the tank full threshold."""
        self._coordinator.tank_full_threshold = value
        self.async_write_ha_state()

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
    """Set up Spectra Watermaker number entities from a config entry."""
    coordinator: SpectraCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[NumberEntity] = [SpectraRunDuration(coordinator)]

    # Only add tank threshold if tank sensors are configured
    if entry.data.get("tank_sensor_port") or entry.data.get("tank_sensor_stbd"):
        entities.append(SpectraTankFullThreshold(coordinator))

    async_add_entities(entities)
