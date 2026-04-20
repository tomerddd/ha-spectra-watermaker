"""Sensor platform for Spectra Watermaker Assistant."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfElectricPotential,
    UnitOfVolume,
    UnitOfTime,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, DEFAULT_MODEL
from .coordinator import SpectraCoordinator
from .models import WaterQuality


@dataclass(frozen=True, kw_only=True)
class SpectraSensorDescription(SensorEntityDescription):
    """Describes a Spectra sensor entity."""

    value_fn: Callable[[SpectraCoordinator], Any] = lambda c: None
    attr_fn: Callable[[SpectraCoordinator], dict[str, Any]] | None = None


def _days_since(iso_timestamp: str | None) -> int | None:
    """Calculate days since an ISO timestamp."""
    if not iso_timestamp:
        return None
    try:
        dt = datetime.fromisoformat(iso_timestamp)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        return max(0, delta.days)
    except (ValueError, TypeError):
        return None


# ──────────────────────────────────────────────
# Sensor descriptions
# ──────────────────────────────────────────────

SENSOR_DESCRIPTIONS: tuple[SpectraSensorDescription, ...] = (
    # ── State ──
    SpectraSensorDescription(
        key="state",
        translation_key="state",
        icon="mdi:water-pump",
        value_fn=lambda c: c.state.value,
    ),
    # ── Real-time sensors (port 9001) ──
    SpectraSensorDescription(
        key="product_flow",
        translation_key="product_flow",
        native_unit_of_measurement=UnitOfVolumeFlowRate.LITERS_PER_HOUR,
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:water-pump",
        suggested_display_precision=1,
        value_fn=lambda c: c.sensor_data.product_flow_lph if c.is_running else None,
    ),
    SpectraSensorDescription(
        key="boost_pressure",
        translation_key="boost_pressure",
        native_unit_of_measurement=UnitOfPressure.PSI,
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda c: c.sensor_data.boost_pressure_psi if c.is_running else None,
    ),
    SpectraSensorDescription(
        key="feed_pressure",
        translation_key="feed_pressure",
        native_unit_of_measurement=UnitOfPressure.PSI,
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda c: c.sensor_data.feed_pressure_psi if c.is_running else None,
    ),
    SpectraSensorDescription(
        key="product_tds",
        translation_key="product_tds",
        native_unit_of_measurement="ppm",
        icon="mdi:water-opacity",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda c: c.sensor_data.product_tds_ppm if c.is_running else None,
    ),
    SpectraSensorDescription(
        key="water_temperature",
        translation_key="water_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda c: c.sensor_data.water_temp_c if c.is_running and c.sensor_data.water_temp_f > 33 else None,
    ),
    SpectraSensorDescription(
        key="water_quality",
        translation_key="water_quality",
        icon="mdi:water-check",
        value_fn=lambda c: c.water_quality.value if c.water_quality else None,
    ),
    SpectraSensorDescription(
        key="water_destination",
        translation_key="water_destination",
        icon="mdi:water-outline",
        value_fn=lambda c: c.water_destination.value if c.is_running else None,
    ),
    SpectraSensorDescription(
        key="filter_condition",
        translation_key="filter_condition",
        native_unit_of_measurement="%",
        icon="mdi:filter",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.filter_condition,
    ),
    SpectraSensorDescription(
        key="elapsed_time",
        translation_key="elapsed_time",
        icon="mdi:timer-outline",
        value_fn=lambda c: c.elapsed_time,
    ),
    SpectraSensorDescription(
        key="remaining_time",
        translation_key="remaining_time",
        icon="mdi:timer-sand",
        value_fn=lambda c: c.remaining_time,
    ),
    # ── Diagnostic sensors ──
    SpectraSensorDescription(
        key="feed_flow",
        translation_key="feed_flow",
        native_unit_of_measurement=UnitOfVolumeFlowRate.LITERS_PER_HOUR,
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value_fn=lambda c: c.sensor_data.feed_flow_lph if c.is_connected else None,
    ),
    SpectraSensorDescription(
        key="feed_tds",
        translation_key="feed_tds",
        native_unit_of_measurement="ppm",
        icon="mdi:water-opacity",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.sensor_data.feed_tds_ppm if c.is_connected else None,
    ),
    SpectraSensorDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=2,
        value_fn=lambda c: c.sensor_data.battery_voltage if c.is_connected else None,
    ),
    SpectraSensorDescription(
        key="autostore_countdown",
        translation_key="autostore_countdown",
        icon="mdi:timer-cog-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.autostore_countdown,
    ),
    SpectraSensorDescription(
        key="flush_progress",
        translation_key="flush_progress",
        native_unit_of_measurement="%",
        icon="mdi:water-sync",
        value_fn=lambda c: c.flush_progress,
    ),
    SpectraSensorDescription(
        key="run_progress",
        translation_key="run_progress",
        native_unit_of_measurement="%",
        icon="mdi:progress-clock",
        suggested_display_precision=0,
        value_fn=lambda c: c.run_progress,
    ),
    # ── Production tracking ──
    SpectraSensorDescription(
        key="total_liters",
        translation_key="total_liters",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        icon="mdi:counter",
        value_fn=lambda c: c.storage.total_liters,
    ),
    SpectraSensorDescription(
        key="current_run_liters",
        translation_key="current_run_liters",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.WATER,
        suggested_display_precision=1,
        icon="mdi:water-plus",
        value_fn=lambda c: c.current_run_liters,
    ),
    SpectraSensorDescription(
        key="total_hours",
        translation_key="total_hours",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        icon="mdi:clock-outline",
        value_fn=lambda c: c.storage.total_hours,
    ),
    # ── Last run sensors ──
    SpectraSensorDescription(
        key="last_run_duration",
        translation_key="last_run_duration",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        icon="mdi:timer",
        suggested_display_precision=0,
        value_fn=lambda c: c.last_run.duration_minutes if c.last_run else None,
    ),
    SpectraSensorDescription(
        key="last_run_avg_ppm",
        translation_key="last_run_avg_ppm",
        native_unit_of_measurement="ppm",
        icon="mdi:water-opacity",
        suggested_display_precision=0,
        value_fn=lambda c: c.last_run.avg_ppm if c.last_run else None,
    ),
    SpectraSensorDescription(
        key="last_run_start",
        translation_key="last_run_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: (
            datetime.fromisoformat(c.last_run.start_time)
            if c.last_run and c.last_run.start_time
            else None
        ),
    ),
    SpectraSensorDescription(
        key="last_run_end",
        translation_key="last_run_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: (
            datetime.fromisoformat(c.last_run.end_time)
            if c.last_run and c.last_run.end_time
            else None
        ),
    ),
    SpectraSensorDescription(
        key="last_run_liters",
        translation_key="last_run_liters",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        icon="mdi:water",
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value_fn=lambda c: c.last_run.liters_produced if c.last_run else None,
    ),
    SpectraSensorDescription(
        key="last_run_time_to_fill",
        translation_key="last_run_time_to_fill",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        icon="mdi:timer-sand",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.last_run.time_to_fill_seconds if c.last_run else None,
    ),
    SpectraSensorDescription(
        key="last_run_stop_reason",
        translation_key="last_run_stop_reason",
        icon="mdi:stop-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.last_run.stop_reason if c.last_run else None,
    ),
    # ── Flush tracking ──
    SpectraSensorDescription(
        key="last_flush",
        translation_key="last_flush",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:water-sync",
        value_fn=lambda c: (
            datetime.fromisoformat(c.storage.last_flush)
            if c.storage.last_flush
            else None
        ),
    ),
    SpectraSensorDescription(
        key="days_since_flush",
        translation_key="days_since_flush",
        native_unit_of_measurement="days",
        icon="mdi:calendar-clock",
        value_fn=lambda c: _days_since(c.storage.last_flush),
    ),
    # ── Prefilter maintenance ──
    SpectraSensorDescription(
        key="prefilter_last_changed",
        translation_key="prefilter_last_changed",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:filter-cog-outline",
        value_fn=lambda c: (
            datetime.fromisoformat(c.storage.prefilter_last_changed)
            if c.storage.prefilter_last_changed
            else None
        ),
    ),
    SpectraSensorDescription(
        key="prefilter_days_ago",
        translation_key="prefilter_days_ago",
        native_unit_of_measurement="days",
        icon="mdi:calendar-alert",
        value_fn=lambda c: _days_since(c.storage.prefilter_last_changed),
    ),
    SpectraSensorDescription(
        key="prefilter_hours_since_change",
        translation_key="prefilter_hours_since_change",
        native_unit_of_measurement=UnitOfTime.HOURS,
        icon="mdi:filter-outline",
        suggested_display_precision=1,
        value_fn=lambda c: c.storage.prefilter_hours,
    ),
)


class SpectraSensor(SensorEntity):
    """Sensor entity for Spectra Watermaker."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SpectraCoordinator,
        description: SpectraSensorDescription,
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
    def available(self) -> bool:
        """Return True if entity is available."""
        # Sensors from storage are always available
        key = self.entity_description.key
        if key in (
            "total_liters",
            "total_hours",
            "last_flush",
            "days_since_flush",
            "prefilter_last_changed",
            "prefilter_days_ago",
            "prefilter_hours_since_change",
            "state",
        ):
            return True
        # Last run sensors available if there's history
        if key.startswith("last_run_"):
            return self._coordinator.last_run is not None
        return self._coordinator.is_connected

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        desc: SpectraSensorDescription = self.entity_description  # type: ignore[assignment]
        return desc.value_fn(self._coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        desc: SpectraSensorDescription = self.entity_description  # type: ignore[assignment]
        if desc.attr_fn:
            return desc.attr_fn(self._coordinator)
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_coordinator_update)
        )

    async def async_will_remove_from_hass(self) -> None:
        """When entity is removed from hass."""
        pass


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Spectra Watermaker sensors from a config entry."""
    coordinator: SpectraCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        SpectraSensor(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
    ]
    async_add_entities(entities)
