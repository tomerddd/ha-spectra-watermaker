"""Binary sensor platform for Spectra Watermaker Assistant."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, DEFAULT_MODEL
from .coordinator import SpectraCoordinator


@dataclass(frozen=True, kw_only=True)
class SpectraBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a Spectra binary sensor entity."""

    is_on_fn: Callable[[SpectraCoordinator], bool | None]


BINARY_SENSOR_DESCRIPTIONS: tuple[SpectraBinarySensorDescription, ...] = (
    SpectraBinarySensorDescription(
        key="connected",
        translation_key="connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda c: c.is_connected,
    ),
    SpectraBinarySensorDescription(
        key="running",
        translation_key="running",
        device_class=BinarySensorDeviceClass.RUNNING,
        icon="mdi:water-pump",
        is_on_fn=lambda c: c.is_running,
    ),
    SpectraBinarySensorDescription(
        key="filling_tank",
        translation_key="filling_tank",
        icon="mdi:water-plus",
        is_on_fn=lambda c: c.is_filling_tank,
    ),
)


class SpectraBinarySensor(BinarySensorEntity):
    """Binary sensor entity for Spectra Watermaker."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SpectraCoordinator,
        description: SpectraBinarySensorDescription,
    ) -> None:
        self.entity_description = description
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.config_entry.entry_id)},
            "name": "Watermaker",
            "manufacturer": MANUFACTURER,
            "model": coordinator.sensor_data.device or DEFAULT_MODEL,
        }

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        desc: SpectraBinarySensorDescription = self.entity_description  # type: ignore[assignment]
        return desc.is_on_fn(self._coordinator)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # Connected sensor is always available
        if self.entity_description.key == "connected":
            return True
        return True  # State-derived sensors are always available

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
    """Set up Spectra Watermaker binary sensors from a config entry."""
    coordinator: SpectraCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        SpectraBinarySensor(coordinator, description)
        for description in BINARY_SENSOR_DESCRIPTIONS
    ]
    async_add_entities(entities)
