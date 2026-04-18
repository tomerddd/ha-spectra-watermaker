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
DEFAULT_TANK_FULL_THRESHOLD = 95
DEFAULT_TANK_FULL_DEBOUNCE_SEC = 30
DEFAULT_COMMAND_DELAY_MS = 1500

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
STATE_STOPPING = "stopping"
STATE_ERROR = "error"

# Stop reasons
STOP_REASON_MANUAL = "manual"
STOP_REASON_TIMER = "timer"
STOP_REASON_TANK_FULL = "tank_full"
STOP_REASON_ERROR = "error"

# Spectra page IDs (running)
PAGES_RUNNING = {"5", "6", "30", "31", "32"}
PAGES_IDLE = {"4", "37", "39", "40", "48", "49"}
PAGES_PROMPT = {"1", "10", "14", "43", "44", "45"}

# Run history
DEFAULT_HISTORY_LIMIT = 50

# PPM stabilization
PPM_IGNORE_STARTUP_SEC = 60
