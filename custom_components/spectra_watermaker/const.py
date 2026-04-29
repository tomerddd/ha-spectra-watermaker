"""Constants for Spectra Watermaker Assistant."""

DOMAIN = "spectra_watermaker"

# Config keys
CONF_HOST = "host"
CONF_POWER_SWITCH = "power_switch"
CONF_POWER_SENSOR = "power_sensor"
CONF_TANK_SENSOR_PORT = "tank_sensor_port"
CONF_TANK_SENSOR_STBD = "tank_sensor_stbd"
CONF_TANK_FULL_THRESHOLD = "tank_full_threshold"
CONF_AUTO_OFF_DELAY = "auto_off_delay"

# Defaults
DEFAULT_WS_UI_PORT = 9000
DEFAULT_WS_DATA_PORT = 9001
DEFAULT_TANK_FULL_THRESHOLD = 98
DEFAULT_TANK_FULL_DEBOUNCE_SEC = 30
DEFAULT_COMMAND_DELAY_MS = 1500
DEFAULT_AUTO_OFF_MINUTES = 5
DEFAULT_RUN_DURATION_HOURS = 2.0

# WebSocket
WS_SUBPROTOCOL = "dumb-increment-protocol"

# State machine states
STATE_OFF = "off"
STATE_BOOTING = "booting"
STATE_PROMPT = "prompt"
STATE_IDLE = "idle"
STATE_STARTING = "starting"
STATE_RUNNING = "running"
STATE_FLUSHING = "flushing"
STATE_ERROR = "error"

# Stop reasons
STOP_REASON_MANUAL = "manual"
STOP_REASON_TIMER = "timer"
STOP_REASON_TANK_FULL = "tank_full"
STOP_REASON_ERROR = "error"
STOP_REASON_POWER_LOSS = "power_loss"
STOP_REASON_DEVICE_REBOOT = "device_reboot"

# Spectra page IDs (running)
PAGES_RUNNING = {"5", "6", "30", "31", "32"}
PAGES_FLUSHING = {"2"}
PAGES_IDLE = {"4", "37", "39", "40", "48", "49"}
PAGES_PROMPT = {"1", "14", "43", "44", "45"}
PAGES_STARTUP = {"10", "101"}  # Page 10 = screensaver/power interrupt/countdown, 101 = init

# Run history
DEFAULT_HISTORY_LIMIT = 50

# PPM stabilization
PPM_IGNORE_STARTUP_SEC = 60

# Water quality levels (TDS ppm thresholds)
QUALITY_EXCELLENT = "excellent"  # < 200 ppm
QUALITY_GOOD = "good"            # 200-350 ppm
QUALITY_ACCEPTABLE = "acceptable"  # 350-500 ppm
QUALITY_POOR = "poor"            # 500-700 ppm
QUALITY_UNDRINKABLE = "undrinkable"  # > 700 ppm

QUALITY_THRESHOLDS = [
    (200, QUALITY_EXCELLENT),
    (350, QUALITY_GOOD),
    (500, QUALITY_ACCEPTABLE),
    (700, QUALITY_POOR),
]
# Above 700 → QUALITY_UNDRINKABLE

# Device info
MANUFACTURER = "Spectra Watermakers"
DEFAULT_MODEL = "Newport 1000"


# ──────────────────────────────────────────────
# Event type
# ──────────────────────────────────────────────

EVENT_SPECTRA_WATERMAKER = "spectra_watermaker_event"

# ──────────────────────────────────────────────
# Model-based anomaly monitoring profiles
# ──────────────────────────────────────────────
# Sources: Spectra programming guide, Newport 700c/1000c manual,
# Spectra support articles, Boundless Outfitters troubleshooting guide.
#
# Thresholds auto-selected from "device" field on port 9001.
# Pressure: PSI, Flow: GPH, TDS: PPM, Temp: °F, Voltage: V.

ANOMALY_STARTUP_SKIP_SEC = 120  # Skip checks for first 2 min of run
PPM_MEMBRANE_REPLACE = 748  # Factory default PPM rejection threshold
FLUSH_TDS_MAX = 1000  # End-of-flush TDS limit (per Spectra)
OPERATING_TEMP_MIN_F = 36
OPERATING_TEMP_MAX_F = 110
BATTERY_VOLTAGE_MIN = 22.0

_RUNNING_CHECKS_TEMPLATE = [
    {
        "metric": "Feed pressure",
        "field": "feed_pressure_psi",
        "min": 100,
        "max": None,  # replaced by pressure_limit
        "causes_low": [
            "Clogged prefilter",
            "Feed pump issue",
            "Air leak in seawater intake",
            "Low boost pump voltage",
        ],
        "causes_high": [
            "Membrane fouling/scaling — needs chemical cleaning",
            "Restriction in brine discharge",
        ],
    },
    {
        "metric": "Boost pressure",
        "field": "boost_pressure_psi",
        "min": 10,
        "max": None,  # replaced by pressure_limit
        "causes_low": [
            "Boost pump failing",
            "Low voltage to pump (need ≥90% of source voltage)",
            "Clogged prefilter reducing flow to boost pump",
        ],
        "causes_high": [
            "Restriction downstream of boost pump",
        ],
    },
    {
        "metric": "Product flow",
        "field": "product_flow_gph",
        "min": None,  # replaced by production_gph * 0.5
        "max": None,  # replaced by production_gph * 1.3
        "causes_low": [
            "Membrane fouling",
            "Low operating pressure",
            "Cold water (expect -50% output at 48°F)",
            "Aged membrane",
        ],
        "causes_high": [
            "O-ring failure allowing salt water bypass into product",
            "Brine seal misaligned — membrane bypass",
            "Sensor calibration issue",
        ],
    },
    {
        "metric": "Product TDS",
        "field": "product_tds_ppm",
        "min": None,
        "max": 500,
        "causes_low": [],
        "causes_high": [
            "Membrane aging (consider replacement at 700-800 ppm)",
            "O-ring leak on product tube end plug",
            "Brine seal misaligned",
            "Membrane bypass",
        ],
    },
    {
        "metric": "Battery voltage",
        "field": "battery_voltage",
        "min": BATTERY_VOLTAGE_MIN,
        "max": None,
        "causes_low": [
            "Insufficient charging",
            "High system load",
            "Battery bank issue",
            "Low voltage = slower pump = less output",
        ],
        "causes_high": [],
    },
    {
        "metric": "Water temperature",
        "field": "water_temp_f",
        "min": OPERATING_TEMP_MIN_F,
        "max": OPERATING_TEMP_MAX_F,
        "causes_low": [
            "Cold water significantly reduces output (per Spectra: -50% at 48°F)",
        ],
        "causes_high": [
            "Above operating range",
            "Possible sensor issue",
        ],
    },
]

_FLUSHING_CHECKS = [
    {
        "metric": "Feed pressure",
        "field": "feed_pressure_psi",
        "min": 10,
        "max": 300,
        "causes_low": [
            "Flush pump not running",
            "Flush valve not opening",
        ],
        "causes_high": [
            "High-pressure pump not disengaged",
            "Valve issue",
        ],
    },
    {
        "metric": "Product flow",
        "field": "product_flow_gph",
        "min": 10,
        "max": 80,
        "causes_low": [
            "Flush pump failure",
            "Flush valve stuck",
            "Charcoal filter clogged (restricting freshwater flow)",
        ],
        "causes_high": [
            "Sensor issue",
        ],
    },
    {
        "metric": "Battery voltage",
        "field": "battery_voltage",
        "min": BATTERY_VOLTAGE_MIN,
        "max": None,
        "causes_low": [
            "Battery depleted during run+flush cycle",
        ],
        "causes_high": [],
    },
]

FLUSH_END_TDS_CHECK = {
    "metric": "End-of-flush TDS",
    "field": "product_tds_ppm",
    "max": FLUSH_TDS_MAX,
    "causes_high": [
        "Flush not effectively cleaning membranes",
        "Insufficient flush water volume",
        "Charcoal filter saturated",
        "Flush duration too short",
    ],
}


def get_model_profile(device_name: str) -> dict:
    """Return anomaly thresholds for the detected device model."""
    import copy

    _MODELS = {
        "NEWPORT 1000": {"pressure_limit": 250, "production_gph": 41},
        "NEWPORT 700": {"pressure_limit": 200, "production_gph": 29},
        "NEWPORT 400": {"pressure_limit": 150, "production_gph": 17},
        "VENTURA 200": {"pressure_limit": 125, "production_gph": 8},
        "VENTURA 150": {"pressure_limit": 125, "production_gph": 6},
        "CATALINA": {"pressure_limit": 130, "production_gph": 14},
    }

    name_upper = device_name.upper() if device_name else ""
    matched = None
    for model_key, model_vals in _MODELS.items():
        if model_key in name_upper:
            matched = model_vals
            break

    if not matched:
        matched = {"pressure_limit": 150, "production_gph": 17}

    pressure_limit = matched["pressure_limit"]
    production_gph = matched["production_gph"]

    running_checks = copy.deepcopy(_RUNNING_CHECKS_TEMPLATE)
    for check in running_checks:
        if check["field"] == "feed_pressure_psi" and check["max"] is None:
            check["max"] = pressure_limit
        if check["field"] == "boost_pressure_psi" and check["max"] is None:
            check["max"] = pressure_limit
        if check["field"] == "product_flow_gph":
            if check["min"] is None:
                check["min"] = round(production_gph * 0.5)
            if check["max"] is None:
                check["max"] = round(production_gph * 1.3)

    return {
        "pressure_limit": pressure_limit,
        "production_gph": production_gph,
        "running_checks": running_checks,
        "flushing_checks": copy.deepcopy(_FLUSHING_CHECKS),
        "flush_end_tds_check": copy.deepcopy(FLUSH_END_TDS_CHECK),
    }
