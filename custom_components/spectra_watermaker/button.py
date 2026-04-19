"""Button platform for Spectra Watermaker Assistant."""
from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, DEFAULT_MODEL
from .coordinator import SpectraCoordinator


@dataclass(frozen=True, kw_only=True)
class SpectraButtonDescription(ButtonEntityDescription):
    """Describes a Spectra button entity."""

    press_fn: Callable[[SpectraCoordinator], Coroutine[Any, Any, Any]]


BUTTON_DESCRIPTIONS: tuple[SpectraButtonDescription, ...] = (
    SpectraButtonDescription(
        key="start",
        translation_key="start",
        icon="mdi:play",
        press_fn=lambda c: c.async_start_watermaker(),
    ),
    SpectraButtonDescription(
        key="stop",
        translation_key="stop",
        icon="mdi:stop",
        press_fn=lambda c: c.async_stop_watermaker(),
    ),
    SpectraButtonDescription(
        key="flush",
        translation_key="flush",
        icon="mdi:water-sync",
        press_fn=lambda c: c.async_flush(),
    ),
    SpectraButtonDescription(
        key="reset_prefilter",
        translation_key="reset_prefilter",
        icon="mdi:filter-remove",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda c: c.async_reset_prefilter(),
    ),
)


class SpectraButton(ButtonEntity):
    """Button entity for Spectra Watermaker."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SpectraCoordinator,
        description: SpectraButtonDescription,
    ) -> None:
        self.entity_description = description
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.config_entry.entry_id)},
            "name": f"Spectra {coordinator.sensor_data.device or DEFAULT_MODEL}",
            "manufacturer": MANUFACTURER,
            "model": coordinator.sensor_data.device or DEFAULT_MODEL,
        }

    async def async_press(self) -> None:
        """Handle the button press."""
        desc: SpectraButtonDescription = self.entity_description  # type: ignore[assignment]
        await desc.press_fn(self._coordinator)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # Reset prefilter is always available
        if self.entity_description.key == "reset_prefilter":
            return True
        return True  # Buttons handle state checks internally


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Spectra Watermaker buttons from a config entry."""
    coordinator: SpectraCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        SpectraButton(coordinator, description)
        for description in BUTTON_DESCRIPTIONS
    ]
    async_add_entities(entities)
