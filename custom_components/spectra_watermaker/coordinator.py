"""DataUpdateCoordinator for Spectra Watermaker."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .client import SpectraClient
from .const import (
    CONF_AUTO_OFF_DELAY,
    CONF_HOST,
    CONF_POWER_SENSOR,
    CONF_POWER_SWITCH,
    CONF_TANK_FULL_THRESHOLD,
    CONF_TANK_SENSOR_PORT,
    CONF_TANK_SENSOR_STBD,
    DEFAULT_AUTO_OFF_MINUTES,
    DEFAULT_RUN_DURATION_HOURS,
    DEFAULT_TANK_FULL_DEBOUNCE_SEC,
    DEFAULT_TANK_FULL_THRESHOLD,
    DEFAULT_WS_DATA_PORT,
    DEFAULT_WS_UI_PORT,
    DOMAIN,
    PPM_IGNORE_STARTUP_SEC,
)
from .models import (
    RunRecord,
    SpectraData,
    SpectraUIState,
    StopReason,
    WaterDestination,
    WatermakerState,
    WaterQuality,
)
from .protocol import SpectraProtocol
from .storage import SpectraHistoryStorage, SpectraStorage

_LOGGER = logging.getLogger(__name__)

# Time after toggle_tank 1->0 before collecting PPM stats
_PPM_POST_TOGGLE_DELAY = 30.0

# How long with both WS down before going to error state
_BOTH_DOWN_TIMEOUT = 30.0


class SpectraCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for Spectra Watermaker.

    Owns the protocol/client, processes callbacks, manages run tracking,
    tank-full auto-stop, and auto power-off.
    """

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,  # Push-based, no polling
        )
        self.config_entry = entry
        self._host: str = entry.data[CONF_HOST]
        self._power_switch: str | None = entry.data.get(CONF_POWER_SWITCH)
        # CONF_POWER_SENSOR is reserved for future use (power-based state fallback)
        self._power_sensor: str | None = entry.data.get(CONF_POWER_SENSOR)
        self._tank_port: str | None = entry.data.get(CONF_TANK_SENSOR_PORT)
        self._tank_stbd: str | None = entry.data.get(CONF_TANK_SENSOR_STBD)

        # Options (with defaults)
        self._tank_full_threshold: float = entry.data.get(
            CONF_TANK_FULL_THRESHOLD, DEFAULT_TANK_FULL_THRESHOLD
        )
        self._auto_off_minutes: int = int(entry.options.get(
            CONF_AUTO_OFF_DELAY, DEFAULT_AUTO_OFF_MINUTES
        ))

        # Protocol layer
        self._client = SpectraClient(
            host=self._host,
            data_port=DEFAULT_WS_DATA_PORT,
            ui_port=DEFAULT_WS_UI_PORT,
            on_data=self._on_data_message,
            on_ui_state=self._on_ui_message,
            on_data_connected=self._on_data_connected,
            on_ui_connected=self._on_ui_connected,
        )
        self._protocol = SpectraProtocol(self._client)
        self._storage = SpectraStorage(hass, entry.entry_id)
        self._history = SpectraHistoryStorage(hass, entry.entry_id)

        # State
        self._state: WatermakerState = WatermakerState.OFF
        self._data: SpectraData = SpectraData()
        self._ui_state: SpectraUIState = SpectraUIState()
        self._data_connected: bool = False
        self._ui_connected: bool = False
        self._both_down_since: float | None = None

        # Run tracking
        self._run_start_time: datetime | None = None
        self._run_liters: float = 0.0
        self._last_saved_liters: float = 0.0
        self._last_incremental_save: float = 0.0
        self._run_ppm_samples: list[float] = []
        self._run_pressure_samples: list[float] = []
        self._run_temp_samples: list[float] = []
        self._run_start_monotonic: float = 0.0
        self._time_to_fill: float | None = None
        self._filling_started: bool = False
        self._ppm_collection_enabled: bool = False
        self._ppm_post_toggle_time: float = 0.0
        self._last_toggle_tank: str = ""
        self._stop_reason: str = StopReason.MANUAL
        self._data_incomplete: bool = False
        self._integration_started: bool = False
        self._last_data_time: float = 0.0

        # Run duration setting
        self._run_duration: float = DEFAULT_RUN_DURATION_HOURS

        # Auto power-off
        self._auto_off_timer: asyncio.TimerHandle | None = None
        self._integration_powered_on: bool = False

        # Tank full debounce
        self._tank_full_timer: asyncio.TimerHandle | None = None
        self._tank_unsub: list[CALLBACK_TYPE] = []

        # Periodic time polling task
        self._time_poll_task: asyncio.Task[None] | None = None

        # Elapsed/remaining time from UI
        self._elapsed_time: str | None = None
        self._remaining_time: str | None = None
        self._filter_condition: float | None = None
        self._flush_progress: float | None = None
        self._autostore_countdown: str | None = None

    # ──────────────────────────────────────────────
    # Public properties
    # ──────────────────────────────────────────────

    @property
    def state(self) -> WatermakerState:
        """Current watermaker state."""
        return self._state

    @property
    def sensor_data(self) -> SpectraData:
        """Latest sensor data from port 9001."""
        return self._data

    @property
    def ui_state(self) -> SpectraUIState:
        """Latest UI state from port 9000."""
        return self._ui_state

    @property
    def is_connected(self) -> bool:
        """Whether at least one WebSocket is connected."""
        return self._data_connected or self._ui_connected

    @property
    def data_connected(self) -> bool:
        """Whether port 9001 is connected."""
        return self._data_connected

    @property
    def ui_connected(self) -> bool:
        """Whether port 9000 is connected."""
        return self._ui_connected

    @property
    def is_running(self) -> bool:
        """Whether watermaker is running or flushing."""
        return self._state in (WatermakerState.RUNNING, WatermakerState.FLUSHING)

    @property
    def is_filling_tank(self) -> bool:
        """Whether actively filling tank (running + water to tank)."""
        return (
            self._state == WatermakerState.RUNNING
            and self._ui_state.water_destination == WaterDestination.TANK
        )

    @property
    def water_destination(self) -> WaterDestination:
        """Current water destination."""
        return self._ui_state.water_destination

    @property
    def water_quality(self) -> WaterQuality | None:
        """Current water quality derived from TDS."""
        if self._state != WatermakerState.RUNNING:
            return None
        if self._data.product_tds_ppm <= 0:
            return None
        return WaterQuality.from_ppm(self._data.product_tds_ppm)

    @property
    def protocol(self) -> SpectraProtocol:
        """Access the protocol layer for commands."""
        return self._protocol

    @property
    def storage(self) -> SpectraStorage:
        """Access persistent storage."""
        return self._storage

    @property
    def history(self) -> SpectraHistoryStorage:
        """Access run history storage."""
        return self._history

    @property
    def run_duration(self) -> float:
        """Configured run duration in hours."""
        return self._run_duration

    @run_duration.setter
    def run_duration(self, value: float) -> None:
        """Set run duration and persist to storage."""
        self._run_duration = max(0.5, min(8.0, value))
        self._storage.run_duration = self._run_duration
        self.hass.async_create_task(
            self._storage.async_save(), name="spectra_save_run_duration"
        )

    @property
    def tank_full_threshold(self) -> float:
        """Tank full auto-stop threshold percentage."""
        return self._tank_full_threshold

    @tank_full_threshold.setter
    def tank_full_threshold(self, value: float) -> None:
        """Set tank full threshold and persist to storage."""
        self._tank_full_threshold = max(50.0, min(100.0, value))
        self._storage.tank_full_threshold = self._tank_full_threshold
        self.hass.async_create_task(
            self._storage.async_save(), name="spectra_save_tank_threshold"
        )

    @property
    def elapsed_time(self) -> str | None:
        """Elapsed time string from UI."""
        return self._elapsed_time

    @property
    def remaining_time(self) -> str | None:
        """Remaining time string from UI."""
        return self._remaining_time

    @property
    def filter_condition(self) -> float | None:
        """Filter condition percentage."""
        return self._filter_condition

    @property
    def flush_progress(self) -> float | None:
        """Flush progress percentage."""
        return self._flush_progress

    @property
    def autostore_countdown(self) -> str | None:
        """Autostore countdown string."""
        return self._autostore_countdown

    @property
    def current_run_liters(self) -> float | None:
        """Liters produced in the current run (None if not running)."""
        if self._state not in (WatermakerState.RUNNING, WatermakerState.FLUSHING):
            return None
        return round(self._run_liters, 1)

    @property
    def run_progress(self) -> float | None:
        """Run progress as a percentage (0-100).

        RUNNING: 0-92% based on elapsed/(elapsed+remaining).
        FLUSHING: 92-100% based on flush gauge progress.
        IDLE/OFF/other: None.
        """
        if self._state == WatermakerState.RUNNING:
            elapsed = self._parse_time_to_minutes(self._elapsed_time)
            remaining = self._parse_time_to_minutes(self._remaining_time)
            if elapsed is None or remaining is None:
                return None
            total = elapsed + remaining
            if total <= 0:
                return None
            return round(elapsed / total * 92.0, 1)
        if self._state == WatermakerState.FLUSHING:
            fp = self._flush_progress
            if fp is None:
                return None
            return round(92.0 + (fp / 100.0 * 8.0), 1)
        return None

    def _parse_time_to_minutes(self, time_str: str | None) -> float | None:
        """Parse a time string like '1h 20m', '45m', '2h' into minutes."""
        if not time_str:
            return None
        time_str = time_str.strip()
        total = 0.0
        hours_match = re.search(r'(\d+)\s*h', time_str)
        mins_match = re.search(r'(\d+)\s*m', time_str)
        if not hours_match and not mins_match:
            return None
        if hours_match:
            total += float(hours_match.group(1)) * 60
        if mins_match:
            total += float(mins_match.group(1))
        return total

    @property
    def last_run(self) -> RunRecord | None:
        """Most recent run record."""
        return self._history.last_run

    @property
    def command_in_progress(self) -> bool:
        """Whether a command sequence is in progress."""
        return self._protocol.command_in_progress

    # ──────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────

    async def async_start(self) -> None:
        """Start the coordinator: load storage, connect WebSockets, subscribe to tanks."""
        await self._storage.async_load()
        await self._history.async_load()

        # Restore persisted number entity values
        if self._storage.run_duration is not None:
            self._run_duration = self._storage.run_duration
        if self._storage.tank_full_threshold is not None:
            self._tank_full_threshold = self._storage.tank_full_threshold

        # Determine initial state based on power switch
        if self._power_switch:
            power_state = self.hass.states.get(self._power_switch)
            if power_state and power_state.state == "off":
                # Outlet is definitively off — don't connect
                self._state = WatermakerState.OFF
            else:
                # Outlet is on, unavailable, or unknown at startup — try to connect.
                # During HA startup, entities may not be loaded yet, so we default
                # to attempting connection rather than assuming off.
                self._state = WatermakerState.BOOTING
                await self._client.connect()
        else:
            # No power switch — assume always powered
            self._state = WatermakerState.BOOTING
            await self._client.connect()

        # Subscribe to tank sensors for auto-stop
        self._subscribe_tanks()

        self.async_set_updated_data({})

    async def async_stop(self) -> None:
        """Stop the coordinator: disconnect WebSockets, cancel timers."""
        self._stop_time_polling()
        self._cancel_auto_off_timer()
        self._cancel_tank_full_timer()

        for unsub in self._tank_unsub:
            unsub()
        self._tank_unsub.clear()

        await self._client.disconnect()
        await self._storage.async_save()
        await self._history.async_save()

    async def _async_update_data(self) -> dict[str, Any]:
        """Not used — push-based coordinator."""
        return {}

    # ──────────────────────────────────────────────
    # Commands
    # ──────────────────────────────────────────────

    async def async_start_watermaker(self, duration_hours: float | None = None) -> bool:
        """Start the watermaker with full sequence.

        Handles power-on, boot prompts, duration setting, and start.
        """
        if self._state == WatermakerState.RUNNING:
            _LOGGER.warning("Watermaker is already running")
            return False

        if self._protocol.command_in_progress:
            _LOGGER.warning("Another command is in progress")
            return False

        duration = duration_hours if duration_hours is not None else self._run_duration
        self._cancel_auto_off_timer()
        self._integration_started = True

        # Power on if needed
        if self._power_switch and self._state == WatermakerState.OFF:
            self._integration_powered_on = True
            _LOGGER.info("Powering on watermaker outlet")
            await self.hass.services.async_call(
                "switch", "turn_on", {"entity_id": self._power_switch}
            )
            self._state = WatermakerState.BOOTING
            self.async_set_updated_data({})

            # Fresh WebSocket connection (resets any stale backoff)
            await self._client.reconnect()

            # Wait for WebSocket connection (up to 60s for boot)
            for _ in range(30):
                if self._ui_connected:
                    break
                await asyncio.sleep(2.0)

            if not self._ui_connected:
                _LOGGER.error("Timeout waiting for WebSocket after power-on")
                self._state = WatermakerState.ERROR
                self.async_set_updated_data({})
                return False

            # Wait for initial UI message
            await asyncio.sleep(2.0)

            # Dismiss boot prompts
            if not await self._protocol.dismiss_prompts():
                _LOGGER.error("Failed to dismiss boot prompts")
                self._state = WatermakerState.ERROR
                self.async_set_updated_data({})
                return False
        elif self._state not in (
            WatermakerState.IDLE,
            WatermakerState.PROMPT,
            WatermakerState.BOOTING,
        ):
            # Need to be idle, prompt, or booting (recovery) to start
            if self._ui_connected and self._ui_state.is_startup_page:
                await self._protocol.dismiss_prompts()
            elif self._state != WatermakerState.IDLE:
                _LOGGER.warning("Cannot start from state %s", self._state)
                return False

        self._state = WatermakerState.STARTING
        self.async_set_updated_data({})

        success = await self._protocol.start(duration)
        if not success:
            self._state = WatermakerState.IDLE if self._ui_connected else WatermakerState.ERROR
            self._integration_started = False
            self.async_set_updated_data({})
            return False

        return True

    async def async_stop_watermaker(self, reason: str = StopReason.MANUAL) -> bool:
        """Stop the watermaker."""
        self._stop_reason = reason
        success = await self._protocol.stop()
        if success:
            _LOGGER.info("Stop command sent (reason: %s)", reason)
        return success

    async def async_flush(self) -> bool:
        """Trigger manual flush."""
        if self._state not in (WatermakerState.IDLE, WatermakerState.PROMPT):
            # Try dismiss prompts first
            if self._state == WatermakerState.OFF and self._power_switch:
                _LOGGER.info("Powering on for flush")
                self._integration_powered_on = True
                await self.hass.services.async_call(
                    "switch", "turn_on", {"entity_id": self._power_switch}
                )
                self._state = WatermakerState.BOOTING
                self.async_set_updated_data({})
                await self._client.connect()
                for _ in range(15):
                    if self._ui_connected:
                        break
                    await asyncio.sleep(2.0)
                if not self._ui_connected:
                    _LOGGER.error("Timeout waiting for WebSocket for flush")
                    return False
                await asyncio.sleep(2.0)
                await self._protocol.dismiss_prompts()

        return await self._protocol.flush()

    async def async_toggle_destination(self) -> bool:
        """Toggle water destination between tank and overboard."""
        return await self._protocol.toggle_destination()

    async def async_reset_prefilter(self) -> None:
        """Reset prefilter tracking to now."""
        self._storage.reset_prefilter()
        await self._storage.async_save()
        self.async_set_updated_data({})

    async def async_power_on(self) -> None:
        """Turn on power switch."""
        if not self._power_switch:
            return
        self._cancel_auto_off_timer()
        self._integration_powered_on = True
        await self.hass.services.async_call(
            "switch", "turn_on", {"entity_id": self._power_switch}
        )
        self._state = WatermakerState.BOOTING
        self.async_set_updated_data({})
        await self._client.reconnect()

        # Wait for WebSocket connection (up to 60s for boot)
        for _ in range(30):
            if self._ui_connected:
                break
            await asyncio.sleep(2.0)

        if not self._ui_connected:
            _LOGGER.warning("Timeout waiting for WebSocket after power-on — state reset to OFF")
            self._state = WatermakerState.OFF
            self._integration_powered_on = False
            self.async_set_updated_data({})

    async def async_power_off(self) -> None:
        """Turn off power switch (only if not flushing)."""
        if not self._power_switch:
            return
        if self._state == WatermakerState.FLUSHING:
            _LOGGER.warning("Cannot power off during flush — waiting for completion")
            return
        self._cancel_auto_off_timer()
        await self._client.disconnect()
        await self.hass.services.async_call(
            "switch", "turn_off", {"entity_id": self._power_switch}
        )
        self._state = WatermakerState.OFF
        self._integration_powered_on = False
        self.async_set_updated_data({})

    # ──────────────────────────────────────────────
    # Callbacks from client
    # ──────────────────────────────────────────────

    @callback
    def _on_data_message(self, data: SpectraData) -> None:
        """Handle port 9001 data message."""
        old_data = self._data
        self._data = data
        self._last_data_time = time.monotonic()

        # Update state from sensor data
        new_state = self._protocol.detect_state(data)
        self._handle_state_transition(new_state)

        # Run tracking: accumulate liters and PPM
        if self._state == WatermakerState.RUNNING and self._run_start_time:
            self._track_run_data(data)

        self.async_set_updated_data({})

    @callback
    def _on_ui_message(self, ui_state: SpectraUIState) -> None:
        """Handle port 9000 UI message."""
        old_ui = self._ui_state
        self._ui_state = ui_state
        self._protocol.update_ui_state(ui_state)

        # Extract time/filter/flush info from UI
        self._extract_ui_data(ui_state)

        # Track toggle_tank transitions
        if old_ui.toggle_tank != ui_state.toggle_tank:
            self._handle_toggle_change(old_ui.toggle_tank, ui_state.toggle_tank)

        # Update state from UI
        new_state = self._protocol.detect_state(self._data)
        self._handle_state_transition(new_state)

        self.async_set_updated_data({})

    @callback
    def _on_data_connected(self, connected: bool) -> None:
        """Handle port 9001 connection state change."""
        self._data_connected = connected
        _LOGGER.info("Data WebSocket (9001) %s", "connected" if connected else "disconnected")

        if connected:
            self._both_down_since = None
            if self._state == WatermakerState.BOOTING:
                # Will be updated by next message
                pass
        else:
            self._check_both_down()

        self.async_set_updated_data({})

    @callback
    def _on_ui_connected(self, connected: bool) -> None:
        """Handle port 9000 connection state change."""
        self._ui_connected = connected
        _LOGGER.info("UI WebSocket (9000) %s", "connected" if connected else "disconnected")

        if connected:
            self._both_down_since = None
        else:
            if self._state == WatermakerState.RUNNING:
                self._data_incomplete = True
            self._check_both_down()

        self.async_set_updated_data({})

    # ──────────────────────────────────────────────
    # State machine
    # ──────────────────────────────────────────────

    def _handle_state_transition(self, new_state: WatermakerState) -> None:
        """Handle state transitions and trigger side effects."""
        old_state = self._state

        # Don't regress from starting to idle during start sequence
        if (
            old_state == WatermakerState.STARTING
            and new_state == WatermakerState.IDLE
            and self._protocol.command_in_progress
        ):
            return

        if old_state == new_state:
            return

        _LOGGER.info("State transition: %s -> %s", old_state, new_state)
        self._state = new_state

        # Entering RUNNING
        if new_state == WatermakerState.RUNNING and old_state != WatermakerState.RUNNING:
            self._start_run_tracking()
            self._start_time_polling()

        # RUNNING -> FLUSHING (normal stop)
        if old_state == WatermakerState.RUNNING and new_state == WatermakerState.FLUSHING:
            self._end_run_tracking()

        # RUNNING -> IDLE (abnormal: flush skipped/interrupted)
        if old_state == WatermakerState.RUNNING and new_state == WatermakerState.IDLE:
            self._end_run_tracking()

        # RUNNING -> anything unexpected
        if old_state == WatermakerState.RUNNING and new_state not in (
            WatermakerState.FLUSHING,
            WatermakerState.IDLE,
            WatermakerState.RUNNING,
        ):
            self._stop_reason = StopReason.ERROR
            self._end_run_tracking()

        # FLUSHING -> IDLE (flush complete)
        if old_state == WatermakerState.FLUSHING and new_state == WatermakerState.IDLE:
            self._stop_time_polling()
            self._on_flush_complete()

        # Check for external start (running without integration commanding it)
        if (
            new_state == WatermakerState.RUNNING
            and not self._integration_started
        ):
            _LOGGER.info("External start detected — tracking run")
            self._integration_powered_on = False

        # Prompt auto-dismiss during boot
        if new_state == WatermakerState.PROMPT and old_state == WatermakerState.BOOTING:
            self.hass.async_create_task(
                self._protocol.dismiss_prompts(),
                name="spectra_dismiss_prompts",
            )

        # Detect device reboot while was running
        if (
            old_state == WatermakerState.RUNNING
            and new_state in (WatermakerState.BOOTING, WatermakerState.PROMPT)
        ):
            self._stop_reason = StopReason.DEVICE_REBOOT

    def _start_run_tracking(self) -> None:
        """Initialize run tracking for a new production run."""
        _LOGGER.info("Starting run tracking")
        self._run_start_time = datetime.now(timezone.utc)
        self._run_start_monotonic = time.monotonic()
        self._run_liters = 0.0
        self._last_saved_liters = 0.0
        self._last_incremental_save = time.monotonic()
        self._run_ppm_samples = []
        self._run_pressure_samples = []
        self._run_temp_samples = []
        self._time_to_fill = None
        self._filling_started = False
        self._ppm_collection_enabled = False
        self._ppm_post_toggle_time = 0.0
        toggle_tank = self._ui_state.toggle_tank
        self._last_toggle_tank = toggle_tank
        self._stop_reason = StopReason.MANUAL
        self._data_incomplete = False
        self._cancel_auto_off_timer()

        # If toggle_tank is already "0" at run start (filling tank from the beginning),
        # mark filling as started immediately and schedule PPM collection to begin
        # after the startup ignore period. The 30s post-toggle delay only applies
        # when toggle changes from 1→0 mid-run.
        if toggle_tank == "0":
            self._filling_started = True
            _LOGGER.info("toggle_tank already 0 at run start — scheduling PPM after %ds", PPM_IGNORE_STARTUP_SEC)
            self.hass.loop.call_later(
                PPM_IGNORE_STARTUP_SEC,
                self._enable_ppm_collection,
            )

    def _enable_ppm_collection(self) -> None:
        """Enable PPM collection — called after the startup ignore period."""
        if self._state == WatermakerState.RUNNING and self._ui_state.toggle_tank == "0":
            _LOGGER.debug("PPM collection enabled after startup ignore period")
            self._ppm_collection_enabled = True

    def _end_run_tracking(self) -> None:
        """Finalize and store the run record."""
        if not self._run_start_time:
            return

        end_time = datetime.now(timezone.utc)
        duration_minutes = (end_time - self._run_start_time).total_seconds() / 60

        avg_ppm = (
            sum(self._run_ppm_samples) / len(self._run_ppm_samples)
            if self._run_ppm_samples
            else None
        )
        min_ppm = min(self._run_ppm_samples) if self._run_ppm_samples else None
        max_ppm = max(self._run_ppm_samples) if self._run_ppm_samples else None
        avg_pressure = (
            sum(self._run_pressure_samples) / len(self._run_pressure_samples)
            if self._run_pressure_samples
            else None
        )
        avg_temp = (
            sum(self._run_temp_samples) / len(self._run_temp_samples)
            if self._run_temp_samples
            else None
        )

        record = RunRecord(
            start_time=self._run_start_time.isoformat(),
            end_time=end_time.isoformat(),
            duration_minutes=round(duration_minutes, 1),
            liters_produced=round(self._run_liters, 1),
            time_to_fill_seconds=(
                round(self._time_to_fill, 0) if self._time_to_fill is not None else None
            ),
            min_ppm=round(min_ppm, 1) if min_ppm is not None else None,
            max_ppm=round(max_ppm, 1) if max_ppm is not None else None,
            avg_ppm=round(avg_ppm, 1) if avg_ppm is not None else None,
            avg_feed_pressure_psi=(
                round(avg_pressure, 1) if avg_pressure is not None else None
            ),
            avg_water_temp_f=round(avg_temp, 1) if avg_temp is not None else None,
            stop_reason=self._stop_reason,
            data_incomplete=self._data_incomplete,
        )

        self._history.add_run(record)
        self.hass.async_create_task(
            self._history.async_save(), name="spectra_save_history"
        )

        # Update totals (only the delta not yet saved incrementally)
        unsaved_liters = self._run_liters - self._last_saved_liters
        self._storage.total_liters += unsaved_liters
        self._storage.total_hours += duration_minutes / 60
        self._storage.prefilter_hours += duration_minutes / 60
        self.hass.async_create_task(
            self._storage.async_save(), name="spectra_save_storage"
        )

        _LOGGER.info(
            "Run complete: %.1f min, %.1f L, avg PPM: %s, reason: %s",
            duration_minutes,
            self._run_liters,
            avg_ppm,
            self._stop_reason,
        )

        self._run_start_time = None
        self._integration_started = False

    def _track_run_data(self, data: SpectraData) -> None:
        """Track per-second production data during a run."""
        elapsed = time.monotonic() - self._run_start_monotonic

        # Accumulate liters: only while toggle_tank == 0 (filling tank)
        if self._ui_state.toggle_tank == "0" and data.product_flow_gph > 0:
            # ~1 sample/sec, so liters = flow_lph / 3600
            self._run_liters += data.product_flow_lph / 3600

        # Incremental save every 60s so liters aren't lost on crash/disconnect
        now = time.monotonic()
        if now - self._last_incremental_save >= 60.0:
            delta = self._run_liters - self._last_saved_liters
            if delta > 0:
                self._storage.total_liters += delta
                self._last_saved_liters = self._run_liters
                self.hass.async_create_task(
                    self._storage.async_save(), name="spectra_incremental_save"
                )
            self._last_incremental_save = now

        # Always collect pressure and temp
        if data.feed_pressure_psi > 0:
            self._run_pressure_samples.append(data.feed_pressure_psi)
        if data.water_temp_f > 32.1:  # Filter out disconnected sensor (32.0F)
            self._run_temp_samples.append(data.water_temp_f)

        # PPM tracking with startup ignore and post-toggle delay
        if elapsed < PPM_IGNORE_STARTUP_SEC:
            return

        if not self._ppm_collection_enabled:
            return

        if self._ui_state.toggle_tank != "0":
            return  # Ignore while overboard

        # Post-toggle delay
        if self._ppm_post_toggle_time > 0:
            if time.monotonic() - self._ppm_post_toggle_time < _PPM_POST_TOGGLE_DELAY:
                return

        if data.product_tds_ppm > 0:
            self._run_ppm_samples.append(data.product_tds_ppm)

    def _handle_toggle_change(self, old_toggle: str, new_toggle: str) -> None:
        """Handle toggle_tank state changes."""
        _LOGGER.debug("toggle_tank changed: %s -> %s", old_toggle, new_toggle)

        if new_toggle == "0" and old_toggle == "1":
            # Water now going to tank
            if not self._filling_started and self._run_start_time:
                # Record time_to_fill
                self._time_to_fill = time.monotonic() - self._run_start_monotonic
                self._filling_started = True
                _LOGGER.info("Water diverted to tank after %.0fs", self._time_to_fill)

            # Start PPM collection after post-toggle delay
            self._ppm_collection_enabled = True
            self._ppm_post_toggle_time = time.monotonic()

        elif new_toggle == "1" and old_toggle == "0":
            # Water diverted overboard — pause PPM collection
            self._ppm_collection_enabled = False

    def _on_flush_complete(self) -> None:
        """Handle flush completion."""
        _LOGGER.info("Flush complete")
        self._storage.last_flush = datetime.now(timezone.utc).isoformat()
        self.hass.async_create_task(
            self._storage.async_save(), name="spectra_save_flush"
        )

        # Start auto power-off timer
        if self._auto_off_minutes > 0:
            self._start_auto_off_timer()

    def _extract_ui_data(self, ui: SpectraUIState) -> None:
        """Extract time/filter/flush data from UI state."""
        page = ui.page

        # Running pages: extract elapsed and remaining time
        # Page 5: label5 = remaining time, label8 = "Tank --" (NOT elapsed)
        # Page 6: label5 = remaining time, label8 = "Tank --" (NOT elapsed)
        # Page 30: label1 = elapsed time (label2 = "Elapsed time")
        # Page 31: label8 = elapsed time (label9 = "Elapsed time")
        # Page 32: no time data
        if page == "5":
            self._remaining_time = ui.label5 if ui.label5 else self._remaining_time
        elif page == "6":
            self._remaining_time = ui.label5 if ui.label5 else self._remaining_time
        elif page == "30":
            if ui.label1 and ui.label2 and "elapsed" in ui.label2.lower():
                self._elapsed_time = ui.label1
        elif page == "31":
            if ui.label8 and ui.label9 and "elapsed" in ui.label9.lower():
                self._elapsed_time = ui.label8

        # Filter condition
        fc = ui.filter_condition_pct
        if fc is not None:
            self._filter_condition = fc

        # Flush progress (page 2)
        if page == "2":
            try:
                self._flush_progress = float(ui.gauge0) if ui.gauge0 else None
            except (ValueError, TypeError):
                self._flush_progress = None
            # Remaining time during flush
            if ui.label1:
                self._remaining_time = ui.label1
        else:
            self._flush_progress = None

        # Autostore countdown (page 4)
        if page == "4" and ui.label1:
            self._autostore_countdown = ui.label1

        # Reset times when not running/flushing
        if page in {"4", "39", "48", "49"}:
            self._elapsed_time = None
            self._remaining_time = None

    # ──────────────────────────────────────────────
    # Tank full auto-stop
    # ──────────────────────────────────────────────

    def _subscribe_tanks(self) -> None:
        """Subscribe to tank sensor state changes."""
        entities: list[str] = []
        if self._tank_port:
            entities.append(self._tank_port)
        if self._tank_stbd:
            entities.append(self._tank_stbd)

        if not entities:
            return

        unsub = async_track_state_change_event(
            self.hass, entities, self._on_tank_state_change
        )
        self._tank_unsub.append(unsub)

    @callback
    def _on_tank_state_change(self, event: Event) -> None:
        """Handle tank level state changes for auto-stop."""
        if self._state != WatermakerState.RUNNING:
            self._cancel_tank_full_timer()
            return

        new_state = event.data.get("new_state")
        if not new_state or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        try:
            level = float(new_state.state)
        except (ValueError, TypeError):
            return

        if level >= self._tank_full_threshold:
            if self._tank_full_timer is None:
                _LOGGER.debug(
                    "Tank %s at %.1f%% (>= %.1f%%), starting %ds debounce",
                    new_state.entity_id,
                    level,
                    self._tank_full_threshold,
                    DEFAULT_TANK_FULL_DEBOUNCE_SEC,
                )
                self._tank_full_timer = self.hass.loop.call_later(
                    DEFAULT_TANK_FULL_DEBOUNCE_SEC,
                    self._tank_full_fire,
                )
        else:
            self._cancel_tank_full_timer()

    def _tank_full_fire(self) -> None:
        """Fire tank-full auto-stop after debounce."""
        self._tank_full_timer = None
        if self._state != WatermakerState.RUNNING:
            return

        _LOGGER.info("Tank full auto-stop triggered (threshold: %.1f%%)", self._tank_full_threshold)
        self.hass.bus.async_fire(
            f"{DOMAIN}_tank_full_stop",
            {"threshold": self._tank_full_threshold},
        )
        self.hass.async_create_task(
            self.async_stop_watermaker(StopReason.TANK_FULL),
            name="spectra_tank_full_stop",
        )

    def _cancel_tank_full_timer(self) -> None:
        """Cancel the tank full debounce timer."""
        if self._tank_full_timer:
            self._tank_full_timer.cancel()
            self._tank_full_timer = None

    # ──────────────────────────────────────────────
    # Auto power-off
    # ──────────────────────────────────────────────

    def _start_auto_off_timer(self) -> None:
        """Start the auto power-off timer."""
        self._cancel_auto_off_timer()
        delay = self._auto_off_minutes * 60
        _LOGGER.info("Auto power-off in %d minutes", self._auto_off_minutes)
        self._auto_off_timer = self.hass.loop.call_later(
            delay, self._auto_off_fire
        )

    def _auto_off_fire(self) -> None:
        """Fire auto power-off."""
        self._auto_off_timer = None
        if self._state not in (WatermakerState.IDLE, WatermakerState.OFF):
            _LOGGER.debug("Auto power-off skipped — state is %s", self._state)
            return
        _LOGGER.info("Auto power-off firing")
        self.hass.async_create_task(
            self.async_power_off(), name="spectra_auto_off"
        )

    def _cancel_auto_off_timer(self) -> None:
        """Cancel the auto power-off timer."""
        if self._auto_off_timer:
            self._auto_off_timer.cancel()
            self._auto_off_timer = None

    # ──────────────────────────────────────────────
    # Periodic time polling
    # ──────────────────────────────────────────────

    def _start_time_polling(self) -> None:
        """Start periodic navigation to page 5 to read elapsed/remaining time."""
        self._stop_time_polling()
        self._time_poll_task = self.hass.async_create_task(
            self._poll_time_loop(), name="spectra_time_poll"
        )

    def _stop_time_polling(self) -> None:
        """Stop time polling."""
        if self._time_poll_task and not self._time_poll_task.done():
            self._time_poll_task.cancel()
            self._time_poll_task = None

    async def _poll_time_loop(self) -> None:
        """Navigate through pages while running to read elapsed and remaining time.

        Remaining time is on pages 5/6, elapsed time is on pages 30/31.
        Cycles: navigate right every 15s to pass through all running pages.
        """
        try:
            while self._state in (WatermakerState.RUNNING, WatermakerState.FLUSHING):
                if (
                    self._ui_connected
                    and not self._protocol.command_in_progress
                ):
                    page = self._ui_state.page
                    if page in ("5", "6", "30", "31", "32", "2"):
                        await self._client.send_command(page, "BUTTON2")
                        await asyncio.sleep(2.0)
                await asyncio.sleep(15.0)
        except asyncio.CancelledError:
            pass

    # ──────────────────────────────────────────────
    # Both-down detection
    # ──────────────────────────────────────────────

    def _check_both_down(self) -> None:
        """Check if both WebSockets are down and transition to error."""
        if not self._data_connected and not self._ui_connected:
            if self._both_down_since is None:
                self._both_down_since = time.monotonic()
                # Schedule a re-check after the timeout elapses
                self.hass.loop.call_later(
                    _BOTH_DOWN_TIMEOUT + 1,
                    self._check_both_down,
                )
            elif time.monotonic() - self._both_down_since > _BOTH_DOWN_TIMEOUT:
                if self._state not in (WatermakerState.OFF, WatermakerState.ERROR):
                    _LOGGER.warning(
                        "Both WebSockets down for >%.0fs, transitioning to error",
                        _BOTH_DOWN_TIMEOUT,
                    )
                    self._state = WatermakerState.ERROR
                    self.async_set_updated_data({})
        else:
            self._both_down_since = None
