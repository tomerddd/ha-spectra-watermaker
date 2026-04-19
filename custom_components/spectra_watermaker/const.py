"""Constants for Spectra Watermaker Assistant."""

DOMAIN = "spectra_watermaker"

# Config keys
CONF_HOST = "host"
CONF_POWER_SWITCH = "power_switch"
CONF_POWER_SENSOR = "power_sensor"
CONF_TANK_SENSOR_PORT = "tank_sensor_port"
CONF_TANK_SENSOR_STBD = "tank_sensor_stbd"
CONF_TANK_FULL_THRESHOLD = "tank_full_threshold"

# Defaults
DEFAULT_WS_UI_PORT = 9000
DEFAULT_WS_DATA_PORT = 9001
DEFAULT_TANK_FULL_THRESHOLD = 98
DEFAULT_TANK_FULL_DEBOUNCE_SEC = 30
DEFAULT_COMMAND_DELAY_MS = 1500
DEFAULT_AUTO_OFF_MINUTES = 5
DEFAULT_RUN_DURATION_HOURS = 2.0

# Config keys
CONF_AUTO_OFF_DELAY = "auto_off_delay"

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
