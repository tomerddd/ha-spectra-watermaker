"""Data models for Spectra Watermaker — standalone, no HA imports."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime


class WatermakerState(enum.StrEnum):
    """Operational state of the watermaker."""

    OFF = "off"
    BOOTING = "booting"
    PROMPT = "prompt"
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    FLUSHING = "flushing"
    ERROR = "error"


class WaterQuality(enum.StrEnum):
    """Water quality derived from TDS/PPM."""

    EXCELLENT = "excellent"
    GOOD = "good"
    ACCEPTABLE = "acceptable"
    POOR = "poor"
    UNDRINKABLE = "undrinkable"

    @classmethod
    def from_ppm(cls, ppm: float) -> WaterQuality:
        """Derive quality level from TDS in ppm."""
        if ppm < 200:
            return cls.EXCELLENT
        if ppm < 350:
            return cls.GOOD
        if ppm < 500:
            return cls.ACCEPTABLE
        if ppm < 700:
            return cls.POOR
        return cls.UNDRINKABLE


class WaterDestination(enum.StrEnum):
    """Where product water is being directed."""

    TANK = "tank"
    OVERBOARD = "overboard"


class StopReason(enum.StrEnum):
    """Why the watermaker stopped."""

    MANUAL = "manual"
    TIMER = "timer"
    TANK_FULL = "tank_full"
    ERROR = "error"
    POWER_LOSS = "power_loss"
    DEVICE_REBOOT = "device_reboot"


@dataclass
class SpectraData:
    """Parsed sensor data from port 9001."""

    device: str = ""
    product_flow_gph: float = 0.0
    feed_flow_gph: float = 0.0
    boost_pressure_psi: float = 0.0
    feed_pressure_psi: float = 0.0
    product_tds_ppm: float = 0.0
    feed_tds_ppm: float = 0.0
    water_temp_f: float = 0.0
    water_temp2_f: float = 0.0
    battery_voltage: float = 0.0
    reg_5v: float = 0.0
    tank_level_1: float = 0.0
    tank_level_2: float = 0.0
    power: int = 0
    lock: int = 0

    # Converted values
    @property
    def product_flow_lph(self) -> float:
        """Product flow in liters per hour."""
        return round(self.product_flow_gph * 3.78541, 2)

    @property
    def feed_flow_lph(self) -> float:
        """Feed flow in liters per hour."""
        return round(self.feed_flow_gph * 3.78541, 2)

    @property
    def water_temp_c(self) -> float:
        """Water temperature in Celsius."""
        return round((self.water_temp_f - 32) * 5 / 9, 1)

    @property
    def is_running(self) -> bool:
        """Determine if watermaker is producing water based on sensor data."""
        return self.product_flow_gph > 0.5 and self.feed_pressure_psi > 100


@dataclass
class SpectraUIState:
    """Parsed UI state from port 9000."""

    page: str = ""
    label0: str = ""
    label1: str = ""
    label2: str = ""
    label3: str = ""
    label4: str = ""
    label5: str = ""
    label6: str = ""
    label7: str = ""
    label8: str = ""
    label9: str = ""
    label10: str = ""
    label11: str = ""
    button0: str = ""
    button1: str = ""
    button2: str = ""
    button3: str = ""
    gauge0: str = ""
    gauge0_label: str = ""
    gauge0_mid: str = ""
    gauge1: str = ""
    gauge1_label: str = ""
    gauge2: str = ""
    gauge2_label: str = ""
    toggle_button: str = ""
    toggle_tank: str = ""
    toggle_level: str = ""
    nav_hide: str = ""
    alarm: str = ""
    tank: str = ""
    logout_button: str = ""

    @property
    def is_running_page(self) -> bool:
        """Check if current page is a running page."""
        return self.page in {"5", "6", "30", "31", "32"}

    @property
    def is_flushing_page(self) -> bool:
        """Check if current page is a flushing page."""
        return self.page == "2"

    @property
    def is_idle_page(self) -> bool:
        """Check if current page is an idle page."""
        return self.page in {"4", "37", "39", "40", "48", "49"}

    @property
    def is_prompt_page(self) -> bool:
        """Check if current page is a prompt/warning page."""
        return self.page in {"1", "14", "43", "44", "45"}

    @property
    def is_startup_page(self) -> bool:
        """Check if current page is a startup/screensaver page."""
        return self.page in {"10", "101"}

    @property
    def water_destination(self) -> WaterDestination:
        """Get current water destination from toggle."""
        return WaterDestination.OVERBOARD if self.toggle_tank == "1" else WaterDestination.TANK

    @property
    def filter_condition_pct(self) -> float | None:
        """Extract filter condition percentage from running pages."""
        if self.page == "32" and self.gauge1_label:
            try:
                return float(self.gauge1_label.replace("%", ""))
            except (ValueError, AttributeError):
                pass
        if self.page == "30" and self.gauge0_label:
            try:
                return float(self.gauge0_label.replace("%", ""))
            except (ValueError, AttributeError):
                pass
        return None


@dataclass
class RunRecord:
    """Record of a single production run."""

    start_time: str = ""  # ISO format
    end_time: str = ""  # ISO format
    duration_minutes: float = 0.0
    liters_produced: float = 0.0
    time_to_fill_seconds: float | None = None
    min_ppm: float | None = None
    max_ppm: float | None = None
    avg_ppm: float | None = None
    avg_feed_pressure_psi: float | None = None
    avg_water_temp_f: float | None = None
    stop_reason: str = StopReason.MANUAL
    data_incomplete: bool = False

    def to_dict(self) -> dict:
        """Serialize to dict for storage."""
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_minutes": self.duration_minutes,
            "liters_produced": self.liters_produced,
            "time_to_fill_seconds": self.time_to_fill_seconds,
            "min_ppm": self.min_ppm,
            "max_ppm": self.max_ppm,
            "avg_ppm": self.avg_ppm,
            "avg_feed_pressure_psi": self.avg_feed_pressure_psi,
            "avg_water_temp_f": self.avg_water_temp_f,
            "stop_reason": self.stop_reason,
            "data_incomplete": self.data_incomplete,
        }

    @classmethod
    def from_dict(cls, data: dict) -> RunRecord:
        """Deserialize from dict."""
        return cls(
            start_time=data.get("start_time", ""),
            end_time=data.get("end_time", ""),
            duration_minutes=data.get("duration_minutes", 0.0),
            liters_produced=data.get("liters_produced", 0.0),
            time_to_fill_seconds=data.get("time_to_fill_seconds"),
            min_ppm=data.get("min_ppm"),
            max_ppm=data.get("max_ppm"),
            avg_ppm=data.get("avg_ppm"),
            avg_feed_pressure_psi=data.get("avg_feed_pressure_psi"),
            avg_water_temp_f=data.get("avg_water_temp_f"),
            stop_reason=data.get("stop_reason", StopReason.MANUAL),
            data_incomplete=data.get("data_incomplete", False),
        )
