# Spectra Newport 1000 — WebSocket Protocol & Integration Reference

## Device Info

- **Model**: Spectra Newport 1000
- **IP**: 192.168.50.25
- **Web UI**: http://192.168.50.25/ (jQuery SPA, no auth required)
- **Connectivity monitor**: `binary_sensor.watermaker_connected` (HA ping integration)
- **Existing HA control**: `switch.outlet_watermaker_switch` (Zigbee outlet, power on/off only)

## WebSocket Endpoints

Both use subprotocol `dumb-increment-protocol`. No authentication. Messages are JSON, ~1/sec.

| Port | Purpose | Use |
|------|---------|-----|
| `ws://192.168.50.25:9000` | UI stream — page state, labels, gauges, button text, mode | Control commands + operational state |
| `ws://192.168.50.25:9001` | Data stream — raw sensor readings | Sensor data (preferred for HA sensors) |

### Connection Example (Python)

```python
import websockets

# Data stream (sensors)
ws_data = await websockets.connect(
    'ws://192.168.50.25:9001',
    subprotocols=['dumb-increment-protocol']
)

# UI stream (control + state)
ws_ui = await websockets.connect(
    'ws://192.168.50.25:9000',
    subprotocols=['dumb-increment-protocol']
)
```

---

## Port 9001 — Data Stream

Pure sensor data, no page navigation required. Every message contains all fields.

### Message Format

```json
{
  "device": "NEWPORT 1000",
  "f_flow": "0.00 gph",
  "p_flow": "47.95 gph",
  "boost_p": "29.35 psi",
  "feed_p": "194.88 psi",
  "sal_1": "295 ppm",
  "sal_2": "27 ppm",
  "temp_1": "82.4 °F",
  "temp_2": "32.0 °F",
  "tank_lvl_1": "-0.62 psi",
  "tank_lvl_2": "-0.62 psi",
  "power": "0",
  "bat_v": "24.43 V",
  "reg_5v": "4.95 V",
  "ph": "0",
  "tank_s_h": "0",
  "tank_s_l": "0",
  "trig": "0",
  "lock": "0"
}
```

### Field Reference

| Field | Unit | Description | Typical Range | Notes |
|-------|------|-------------|---------------|-------|
| `device` | — | Model identifier | "NEWPORT 1000" | Static |
| `p_flow` | gph | Product (fresh water) flow rate | 0–50 gph | Key production metric |
| `f_flow` | gph | Feed (seawater) flow rate | 0–? gph | Reads 0 on our unit |
| `boost_p` | psi | Boost pump pressure | ~29 psi when running | Pre-membrane |
| `feed_p` | psi | Membrane feed pressure | ~195 psi when running | Main operating pressure |
| `sal_1` | ppm | Product water TDS (Total Dissolved Solids) | 290–310 ppm running | Primary quality indicator — see Water Quality section |
| `sal_2` | ppm | Feed water TDS | ~27 ppm | Seawater reference |
| `temp_1` | °F | Water temperature | ~82 °F | Seawater intake temp |
| `temp_2` | °F | Secondary temperature | 32.0 °F | Not connected (reads 32) |
| `bat_v` | V | Battery/supply voltage | 24.3–24.5 V | 24V DC supply |
| `reg_5v` | V | Internal 5V regulator | ~4.95 V | Board health check |
| `tank_lvl_1` | psi | Tank level sensor 1 | -0.62 psi | Not connected |
| `tank_lvl_2` | psi | Tank level sensor 2 | -0.62 psi | Not connected |
| `ph` | — | pH sensor | 0 | Not connected |
| `tank_s_h` | — | Tank switch high | 0 | Not connected |
| `tank_s_l` | — | Tank switch low | 0 | Not connected |
| `power` | — | Power mode flag | 0 | |
| `trig` | — | Trigger state | 0 | |
| `lock` | — | Lockout state | 0 | |

### Unit Conversions (to SI / metric)

| From | To | Formula |
|------|----|---------|
| psi | Pa | `× 6894.76` |
| psi | bar | `× 0.0689476` |
| gph | L/h | `× 3.78541` |
| °F | °C | `(F - 32) × 5/9` |
| °F | K | `(F - 32) × 5/9 + 273.15` |

### Parsing Note

Values include units in the string (e.g., `"47.95 gph"`). Parse the numeric portion:

```python
float(value.split()[0])  # "47.95 gph" -> 47.95
```

---

## Port 9000 — UI Stream

Mirrors the Spectra Connect touchscreen display. Messages contain page ID, label text, gauge values, button labels, and toggle states. Page changes when navigating or when the system changes state.

### Message Format (while running, page 32 — Main Dashboard)

```json
{
  "page": "32",
  "button0": "STOP",
  "label0": "AUTORUN : MAIN DASHBOARD",
  "gauge0_label": "194.7psi",
  "gauge0": "77",
  "label1": "Feed Pressure",
  "gauge1_label": "100%",
  "gauge1": "100",
  "label2": "Filter Condition",
  "gauge2_label": "294ppm",
  "gauge2": "29",
  "label3": "Quality",
  "toggle_button": "1",
  "toggle_tank": "0",
  "gauge0_mid": "270"
}
```

### Running Pages (cycle with left/right arrows)

| Page | Title | Key Data |
|------|-------|----------|
| **32** | AUTORUN : MAIN DASHBOARD | Feed pressure (gauge0), filter condition (gauge1), quality/TDS (gauge2) |
| **5** | AUTORUN : PRODUCT | Quality ppm (gauge0), flow rate gph (gauge1), remaining time, tank level |
| **6** | AUTORUN : PRESSURE | Boost pressure (gauge0), feed pressure (gauge1), remaining time |
| **30** | AUTORUN : PREFILTER CONDITION | Filter % (gauge0), elapsed time, boost pressure |
| **31** | AUTORUN : SYSTEM DATA | All readings as text — flow, boost, feed, quality, temp, voltage, filter % |

### Page 31 — System Data (all values in one place)

```json
{
  "page": "31",
  "label0": "AUTORUN : SYSTEM DATA",
  "label1": " Gallons per hour : 48.0 gph",
  "label2": " Boost Pressure   : 29.3 psi",
  "label3": " Feed Pressure    : 194.4 psi",
  "label4": " Product quality  : 294 ppm",
  "label5": " Water temperature: 82.40 F",
  "label6": " Voltage          : 24.43 V",
  "label7": " Filter condition : 100%",
  "label8": "14m",
  "label9": "Elapsed time",
  "label10": "!",
  "label11": "Tank --",
  "toggle_button": "1",
  "toggle_tank": "0",
  "toggle_level": "0",
  "nav_hide": "0"
}
```

### Toggle States

| Field | Value 0 | Value 1 | Value 2 |
|-------|---------|---------|---------|
| `toggle_tank` | Filling tank | Water overboard | — |
| `toggle_button` | Low speed | High speed | — |
| `toggle_level` | Hidden | Toggle off image | Toggle on image |

### Gauge Values

Gauge numeric values (`gauge0`, `gauge1`, `gauge2`) are 0–100 representing percentage of arc fill (multiplied by 3.6 for degrees). The `gauge0_mid` value sets the threshold where the gauge color changes from blue to red.

---

## Sending Commands (Port 9000)

Commands are JSON sent on the same WebSocket connection. Format:

```json
{"page": "<current_page>", "cmd": "BUTTON<n>"}
```

**Important**: Always use the current page number. Allow **1500ms** between sequential commands.

### Commands While Running (pages 5, 6, 30, 31, 32)

| Command | Action |
|---------|--------|
| `{"page":"<cur>","cmd":"BUTTON0"}` | **STOP** the watermaker |
| `{"page":"<cur>","cmd":"BUTTON1"}` | Navigate LEFT |
| `{"page":"<cur>","cmd":"BUTTON2"}` | Navigate RIGHT |
| `{"page":"<cur>","cmd":"BUTTON3"}` | Toggle: tank fill vs. overboard |
| `{"page":"<cur>","cmd":"BUTTON4"}` | Toggle: tank level adjust |

### Commands While Idle

Idle pages vary by model/firmware (pages 4, 37, 39, 40, 48, 49). Check `label0` for mode.

| Command | Action |
|---------|--------|
| `BUTTON0` | Start (large button) or primary action |
| `BUTTON1` | Secondary start / flush |
| `BUTTON2` | Tertiary option |
| `BUTTON4` | Menu / settings |
| `BUTTON6` | Logout |

### Other Command Types

```json
// Cancel (e.g., dismiss dialog)
{"page": "<cur>", "cmd": "CANCEL"}

// Help
{"page": "<cur>", "cmd": "HELP"}

// Data input (e.g., set run quantity in liters/hours)
{"page": "<cur>", "data": "100"}

// Click on labeled input field
{"page": "<cur>", "cmd": "LABEL<n>"}
```

### Start Sequences

**Start Autorun** — confirmed sequence for Newport 1000 (1500ms between each step):
```
{"page":"10","cmd":"BUTTON0"}   # Dismiss screensaver (if on page 10)
{"page":"4","cmd":"BUTTON1"}    # Press START
{"page":"37","cmd":"BUTTON0"}   # Select AUTORUN (only option on Newport 1000)
{"page":"29","cmd":"BUTTON2"}   # Select hours (button1=gallons, button2=hours)
{"page":"29","cmd":"BUTTON3"}   # Press OK (uses current amount value)
  → Page 10: "System starting : 8" (8-second countdown)
  → Page 32: AUTORUN : MAIN DASHBOARD (running)
```

**Setting quantity**: To change the amount, click `LABEL0` on page 29 which opens page 12 (text input), send `{"page":"12","data":"1.5"}`, then back on page 29 press `BUTTON3` (OK). Default value persists between runs.

**Note**: Page 37 only shows `AUTORUN` on the Newport 1000 (button1 and button2 are empty). Other Spectra models may show additional options like "Fill Tank".

**Manual flush from idle** (single command):
```
{"page":"4","cmd":"BUTTON0"}    # Press FRESH WATER FLUSH
```

**Stop** (single command, works from running or flushing):
```
{"page":"<cur>","cmd":"BUTTON0"}
```

**Confirmed idle page 4 button mapping:**
- `BUTTON0` = Fresh Water Flush
- `BUTTON1` = Start
- `BUTTON2` = Stop (no-op when idle)

---

## Operational State Detection

### From Port 9000 (`label0`)

| `label0` prefix | State |
|-----------------|-------|
| `AUTORUN :` | Running |
| `FLUSH :` or `FRESHWATER FLUSH` | Flushing |
| Contains `STANDBY` or idle page (4/37/39/48/49) | Idle/Standby |
| `CONNECTION PENDING` (page 102) | WebSocket connected, device offline |
| `DISPLAY UPDATING` (page 101) | Firmware update in progress |

### From Port 9001

When idle/stopped, `p_flow` will be `0.00 gph` and pressures will drop to near zero. No explicit state field exists on port 9001 — derive state from sensor values or use port 9000.

---

## Idle Page Map (from HTML templates)

| Page | Type | Buttons | Context |
|------|------|---------|---------|
| 4 | Main idle (3 buttons + menu) | 0=primary, 1=secondary, 2=tertiary, 4=menu, 6=logout | Standard idle |
| 37 | Run mode selector (large + 2 small) | 0=fill tank, 1=autofill, 4=back | After pressing Start |
| 39 | Main idle (3 buttons + 2 gauges) | 0–2=actions, 4=menu, 6=logout | Alternate layout |
| 40 | Run mode selector (large + 2 small + 2 gauges) | 0=fill tank, 1=autofill, 4=back | Alternate layout |
| 48 | Main idle (large + long button + 2 gauges) | 0=start, 1=long-press, 4=menu, 6=logout | Newer firmware? |
| 49 | Main idle (large + long button + 1 gauge) | 0=start, 1=long-press, 4=menu, 6=logout | Simpler layout |

## Settings/Menu Pages (from HTML templates, accessible from idle)

| Page | Purpose |
|------|---------|
| 7, 8, 33, 46 | Menu lists (settings categories) |
| 9, 36, 42 | Calibration inputs |
| 13 | Login (username/password) |
| 15 | Brightness slider |
| 16 | Password change |
| 17, 35 | Log viewer (multi-tab) |
| 18 | Config dropdown selector |
| 19 | 10-button command grid |
| 20 | Unit system (metric/imperial) |
| 21 | Dual-value settings |
| 22, 24, 27 | Sensor/alarm thresholds with enable checkboxes |
| 23, 26, 47 | Multi-checkbox settings |
| 25 | Stats page (text + gauge + tank level toggle) |
| 28 | Single checkbox + warning label |
| 29 | Autorun mode (quantity input + liters/hours radio) |
| 34 | Service intervals (hours counters with reset buttons) |
| 41, 50 | Checkbox + value settings |
| 51 | 5-field settings form |

---

## Existing Integration Options

### 1. SignalK Plugin (existing, tested)

**Repo**: https://github.com/htool/signalk-spectra-plugin

Connects to both ports, publishes to SignalK paths, accepts PUT commands for start/stop/toggle. Could bridge to HA via our existing SignalK -> MQTT pipeline.

SignalK control paths:
- `watermaker.spectra.control.start` — accepts `{"mode":"filltank"}` or `{"mode":"autofill","hours":1}` or `{"mode":"autofill","liters":100}`
- `watermaker.spectra.control.stop`
- `watermaker.spectra.control.toggleSpeed`
- `watermaker.spectra.control.lookupStats`

### 2. Direct Python Daemon

A standalone Python script maintaining WebSocket connections and publishing to HA via REST API or MQTT. More control, fewer moving parts.

### 3. BoatHackers Reference

Blog post documenting the same reverse-engineering approach: https://boathackers.com/automating-spectra-newport-400c-watermaker/

The author planned but never published a Home Assistant integration.

---

## Current HA Integration (power-based, pre-WebSocket)

Existing entities derived from the Zigbee outlet power draw:

```yaml
# configuration.yaml
- name: "Watermaker Status"
  state: >
    {% set power = states('sensor.outlet_watermaker_power') | float(0) %}
    {% set sw = states('switch.outlet_watermaker_switch') %}
    {% if sw == 'off' %}Off
    {% elif power < 5 %}Idle
    {% elif power < 250 %}Flushing
    {% elif power < 1000 %}Flushing
    {% else %}Running{% endif %}

- name: "Watermaker Running"
  state: >
    {{ states('sensor.watermaker_status') in ['Running', 'Flushing'] }}
```

These can be enhanced or replaced with WebSocket-derived data for much richer monitoring.

---

## Water Quality — TDS Reference

**TDS (Total Dissolved Solids)** measures the total concentration of dissolved substances in water, in parts per million (ppm). For reverse osmosis systems, it's the primary metric for membrane performance — how well the membrane rejects salt from seawater (~35,000 ppm).

### Quality Levels

| Level | TDS (ppm) | Description | Action |
|-------|-----------|-------------|--------|
| **Excellent** | < 200 | Fresh/cleaned membranes, optimal conditions | None |
| **Good** | 200–350 | Normal operating range for Spectra Newport | None |
| **Acceptable** | 350–500 | Within WHO/EPA guidelines, trending up | Monitor trend |
| **Poor** | 500–700 | Membrane performance declining | Schedule membrane cleaning, check O-rings/seals |
| **Undrinkable** | > 700 | Excessive salt passage | Divert overboard, do not fill tanks. Clean or replace membranes |

### Context

- **Salt rejection %** = `(1 - product_TDS / feed_TDS) × 100`. At 300 ppm from 35,000 ppm seawater = **99.14% rejection** — good.
- **Spectra Newport systems** use lower-pressure energy recovery, so TDS is typically higher (200–350 ppm) than traditional high-pressure RO (100–200 ppm). This is by design.
- **WHO guideline**: < 600 ppm is "good palatability", up to 1,000 ppm is acceptable.
- **US EPA secondary standard**: < 500 ppm recommended.
- **Spectra recommendation**: product water under 500 ppm; clean membranes when TDS rises 15–20% above baseline.

### Factors Affecting TDS

- **Water temperature**: warmer = lower TDS (better membrane flux)
- **Feedwater salinity**: varies by location (coastal, open ocean, near rivers)
- **Membrane age**: gradual TDS rise over months is normal aging
- **Sudden TDS jump**: suggests seal failure, O-ring issue, or membrane damage — not normal wear
- **Run startup**: first minutes produce higher TDS until system stabilizes (integration ignores this)

### Integration Behavior

- `sensor.spectra_water_quality` updates in real-time from `sal_1` readings
- Only evaluates quality while state is `running` and `toggle_tank` == `0` (filling tank)
- During startup/overboard divert, sensor shows last known quality or `unknown`
- Run history stores min/max/avg TDS per run (after stabilization) for long-term trend tracking
- `time_to_fill` metric (seconds from start until water diverts to tank) also trends with membrane health

## Safety Notes

- The Spectra Connect has **no authentication** on its WebSocket — anyone on the network can send commands.
- Always confirm page state before sending commands (read a message first, verify the page number).
- Use 1500ms delays between sequential commands to avoid race conditions.
- The `lock` field on port 9001 may indicate a lockout condition — do not send start commands when `lock` is `1`.
- Monitor `sal_1` (product TDS) — if quality degrades significantly, the watermaker should divert to overboard automatically, but a safety automation in HA is prudent.

---

## Boot-Up Behavior (Power Cycle Recovery)

The Spectra Connect module is powered via a switchable outlet (`switch.outlet_watermaker_switch`). When the outlet is off, the Spectra is fully powered down. On power-up, the system goes through a startup sequence that requires user acknowledgment before it becomes operational.

### Observed Boot Prompts

1. **Power loss warning** — The system detects it was not shut down gracefully (because we cut power at the outlet). It shows a warning message with a beep/alarm and requires pressing an "OK" button to dismiss.

2. **"Was system stored with chemicals?"** — Sometimes appears after power-up. The correct answer for our boat is **No**. Answering Yes would trigger a chemical flush sequence we don't need.

These are likely dialog pages (page templates 1, 10, 14, 43, 44, or 45 based on the HTML — warning/confirmation pages with 1-2 buttons). The integration must:
- Detect these prompt pages after power-on
- Auto-dismiss the power loss warning (click OK / BUTTON0)
- Auto-answer "No" to the chemical storage question (identify which button is "No" from the label text)
- Wait for the system to reach an idle page (4/39/48/49) before attempting start commands

### Boot Sequence (expected flow)

```
Outlet ON
  → Spectra powers up (~5-10s)
  → ping becomes responsive (binary_sensor.watermaker_connected)
  → WebSocket port 9000 becomes available
  → Page 102 "CONNECTION PENDING" briefly
  → Warning/prompt page(s) appear (need OK / No)
  → System reaches idle page (ready for commands)
```

### Confirmed Boot Sequence (tested 2026-04-18)

Power off → 5s wait → Power on:

1. **~11 seconds** — WebSocket not available (device booting)
2. **Page 101** — blank page, displayed briefly during internal init
3. **Page 10** — `"POWER INTERRUPT"` warning with `alarm: "ON"` (beep). `button0: "OK"`. Send `BUTTON0` to dismiss.
4. **Page 4** — idle, ready for commands

No "chemical storage" prompt appeared in this test (may only appear after extended power-off periods).

**Auto-dismiss logic for integration:**
- Page 101: ignore, wait
- Page 10 with `label0` containing `"POWER INTERRUPT"`: send `BUTTON0` (OK)
- Page 10 with `label0` containing `"AUTOSTORE"`: send `BUTTON0` (dismiss screensaver)
- Pages 1/44/45 with `label0` containing `"chemical"` or `"stored"`: send the "No" button (identify from label text)
- Page 4: boot complete, system idle

---

## HACS Custom Integration — Design Intent

Goal: Build a proper Home Assistant custom integration (`spectra_watermaker`) publishable to HACS. No existing HA integration for Spectra watermakers exists — this would be the first.

### Config Flow (UI Setup)

The integration should be configurable entirely through the HA UI (config flow), no YAML:

1. **Watermaker IP address** — the Spectra Connect module IP (e.g., `192.168.50.25`)
2. **Power outlet switch** (optional) — entity selector for a `switch.*` entity that controls AC/DC power to the watermaker. Used to power-on before starting, power-off after idle, and detect power state.
3. **Power sensor** (optional) — entity selector for a `sensor.*` entity that measures the outlet's power draw (W). Used as a secondary state confirmation and for the existing power-based status logic as fallback.
4. **Tank sensor — port** (optional) — entity selector for a `sensor.*` that provides port tank level (%). May come from SignalK, Victron, or any other system.
5. **Tank sensor — starboard** (optional) — entity selector for a `sensor.*` that provides starboard tank level (%).
6. **Tank full auto-stop threshold** (optional, default: 95%) — `number` input (50–100%). When any configured tank sensor stays at or above this value for 30 continuous seconds, the integration sends a stop command. The 30s debounce avoids false triggers from sensor noise/sloshing.

### Entities to Create

**Sensors** (from port 9001 data stream):

| Entity | Source field | Unit | Device class |
|--------|-------------|------|--------------|
| `sensor.spectra_product_flow` | `p_flow` | L/h (converted) | `water` |
| `sensor.spectra_feed_flow` | `f_flow` | L/h (converted) | `water` |
| `sensor.spectra_boost_pressure` | `boost_p` | psi | `pressure` |
| `sensor.spectra_feed_pressure` | `feed_p` | psi | `pressure` |
| `sensor.spectra_product_tds` | `sal_1` | ppm | — |
| `sensor.spectra_feed_tds` | `sal_2` | ppm | — |
| `sensor.spectra_water_temperature` | `temp_1` | °C (converted) | `temperature` |
| `sensor.spectra_battery_voltage` | `bat_v` | V | `voltage` |
| `sensor.spectra_filter_condition` | from port 9000 | % | — |
| `sensor.spectra_elapsed_time` | from port 9000 | — | `duration` |
| `sensor.spectra_remaining_time` | from port 9000 | — | `duration` |
| `sensor.spectra_flush_remaining` | from port 9000 | — | `duration` |
| `sensor.spectra_flush_progress` | from port 9000 page 2 gauge0 | % | — |
| `sensor.spectra_autostore_countdown` | from port 9000 page 4 label1 | — | `duration` |

**Maintenance sensors**:

| Entity | Type | Description |
|--------|------|-------------|
| `sensor.spectra_prefilter_last_changed` | `timestamp` | Date prefilters were last replaced. User-settable via service or button. Persisted in `config_entry` options or `.storage`. |
| `sensor.spectra_prefilter_days_ago` | `int` (days) | Days since last prefilter change. Derived from above timestamp. Useful for automations (e.g., notify when > 90 days). |

**Run history sensors**:

| Entity | Type | Description |
|--------|------|-------------|
| `sensor.spectra_last_run_start` | `timestamp` | When the last production run started |
| `sensor.spectra_last_run_end` | `timestamp` | When the last production run ended (transition to flushing) |
| `sensor.spectra_last_run_duration` | `duration` | Total production time of last run (excludes flush) |
| `sensor.spectra_last_run_liters` | `float` (L) | Estimated liters produced in last run (flow rate integrated over time) |
| `sensor.spectra_total_liters_today` | `float` (L) | Total liters produced today (utility meter style, resets daily) |

**Tank sensors** (from configured external entities):

| Entity | Description |
|--------|-------------|
| `sensor.spectra_tank_port_level` | Mirror of configured port tank sensor (%) |
| `sensor.spectra_tank_stbd_level` | Mirror of configured starboard tank sensor (%) |
| `binary_sensor.spectra_tank_full` | True when any configured tank >= threshold for 30s |

**Binary sensors**:

| Entity | Logic |
|--------|-------|
| `binary_sensor.spectra_connected` | WebSocket connection alive |
| `binary_sensor.spectra_running` | State is running or flushing |
| `binary_sensor.spectra_filling_tank` | True when running AND water going to tank (not diverting overboard) |

**Select / state**:

| Entity | Values |
|--------|--------|
| `sensor.spectra_state` | `off`, `booting`, `prompt`, `idle`, `starting`, `running`, `flushing`, `stopping`, `error` |
| `sensor.spectra_water_destination` | `tank`, `overboard` |
| `sensor.spectra_water_quality` | `excellent`, `good`, `acceptable`, `poor`, `undrinkable` — derived from `sal_1` TDS |

**Controls** (services and/or buttons):

| Entity / Service | Action |
|------------------|--------|
| `button.spectra_start_fill_tank` | Power on (if outlet configured) → wait for idle → start fill tank |
| `button.spectra_start_autofill` | Start autofill (with configurable default quantity) |
| `button.spectra_stop` | Send stop command |
| `button.spectra_flush` | Trigger freshwater flush |
| `switch.spectra_watermaker` | On = start fill tank, Off = stop (simple toggle for dashboard) |
| `select.spectra_water_destination` | Toggle tank vs. overboard |
| `button.spectra_reset_prefilter` | Reset prefilter last-changed date to now |
| `number.spectra_tank_full_threshold` | Auto-stop threshold (50–100%, default 95) |

### State Machine

```
                          ┌─────────────┐
         outlet_on()      │             │
    ┌──────────────────── │     OFF     │ ◄── outlet is off
    │                     │             │
    │                     └─────────────┘
    ▼                           ▲
┌─────────┐                     │ outlet_off()
│ BOOTING │ ── ws connects ──►  │
└─────────┘                     │
    │                           │
    │ prompt page detected      │
    ▼                           │
┌─────────┐                     │
│ PROMPT  │ ── auto-dismiss ──► │
└─────────┘                     │
    │                           │
    │ idle page reached         │
    ▼                           │
┌─────────┐   start cmd   ┌─────────┐
│  IDLE   │ ─────────────► │ RUNNING │
└─────────┘                └─────────┘
    ▲                           │
    │                      stop cmd / timer ends / tank full
    │                           │
    │                     ┌──────────┐
    │ ◄────────────────── │ FLUSHING │ (auto-flush, 3-10 min)
    │                     └──────────┘
```

### Flush Phase

After stop (manual or timer/tank-full auto-stop), the watermaker enters a **freshwater flush** cycle:
- **Page 2** — a distinct page, not part of the running or idle page sets
- `label0`: `"FLUSH"`
- `label1`: `"Remaining time : 8m"` (text with remaining time)
- `gauge0`: progress percentage (0 → 100), NOT a countdown timer
- `button0`: `"STOP"` — user can abort flush (not recommended)
- Duration: ~8 minutes observed (may vary 3–10 min)
- Power draw drops noticeably (lower than running, higher than idle) — this is how the existing power-based template detects it
- The system transitions to **page 4 (idle)** automatically when flush completes
- **Do not cut power during flush** — the flush protects the membranes. The integration should block outlet-off until flush completes or a safety timeout elapses.
- After flush completes and system reaches idle, it is safe to power off the outlet.

### Idle Page (Page 4) — Confirmed Layout

After a run completes (or on boot), the system shows page 4:

```json
{
  "page": "4",
  "button0": "FRESH WATER FLUSH",
  "button1": "START",
  "button2": "STOP",
  "label0": "NEWPORT 1000",
  "label1": "Autostore : 29d 23h 59m",
  "label2": "Tank Level",
  "label4": "",
  "gauge0": "0",
  "gauge0_label": "!",
  "logout_button": "0",
  "tank": "1055"
}
```

**Buttons on idle page 4:**
- `button0` = **FRESH WATER FLUSH** (manual flush)
- `button1` = **START** (begin production)
- `button2` = **STOP** (no-op when already idle)

**Data on idle page 4:**
- `label0` = device model name ("NEWPORT 1000")
- `label1` = autostore countdown ("Autostore : 29d 23h 59m") — days until next scheduled chemical preservation flush
- `gauge0` / `gauge0_label` = tank level (shows "!" when not connected)

### Power Management Integration

When a power outlet switch is configured:
- **Start**: Turn on outlet → wait for ping → wait for WebSocket → auto-dismiss prompts → send start command
- **Stop**: Send stop command → wait for flush to complete → (optionally) turn off outlet after idle timeout
- **State "off"**: Outlet is off, no WebSocket expected
- **State "booting"**: Outlet is on, waiting for WebSocket connection

When no outlet is configured:
- Assume the watermaker is always powered
- Skip power-on/off steps, start directly from idle

### HACS Publication Requirements

- Repository structure: `custom_components/spectra_watermaker/`
- Required files: `manifest.json`, `__init__.py`, `config_flow.py`, `sensor.py`, `binary_sensor.py`, `button.py`, `switch.py`, `select.py`, `const.py`, `strings.json`, `translations/en.json`
- HACS category: `integration`
- Needs `hacs.json` in repo root
- GitHub repository with releases/tags
- Brand assets: icon, logo for the integration page
- Documentation: README with setup instructions, screenshots

### Tank Full Auto-Stop

When one or both tank sensors are configured:
- The coordinator subscribes to the tank entity state changes
- When any tank level >= threshold, a 30-second timer starts
- If the level stays >= threshold for the full 30 seconds, the integration sends a stop command
- The 30s debounce prevents false stops from wave-induced sloshing or sensor noise
- Timer resets if level drops below threshold during the window
- Auto-stop only fires when state is `running` (not during flush or idle)
- Fires a `spectra_watermaker_tank_full_stop` event so automations can react (e.g., send notification)
- The stop triggers the normal flush cycle — the integration does NOT cut power until flush completes

### Prefilter Maintenance Tracking

- `sensor.spectra_prefilter_last_changed` stores a datetime, persisted across restarts
- `button.spectra_reset_prefilter` sets it to `now()` and persists
- `sensor.spectra_prefilter_days_ago` is a derived template: `(now() - last_changed).days`
- Storage: use `config_entry` options (survives uninstall/reinstall) or a dedicated `.storage/spectra_watermaker` JSON file
- Suggested automation (user creates, not built-in): notify when days_ago > 90

### Run History & Logging

The integration tracks each production run. A "run" starts when state transitions to `running` and ends when it transitions to `flushing` (or `idle` if flush is skipped/interrupted).

#### Water Quality (TDS/PPM) Tracking

The `toggle_tank` field on port 9000 indicates whether product water is going to the tank (`0`) or overboard (`1`). At the start of a run, the watermaker diverts water overboard until salinity drops below an acceptable threshold, then switches to filling the tank.

**Filling state entity**: `binary_sensor.spectra_filling_tank` — True when `toggle_tank` == `0` and state is `running`. Exposed so users can see/automate on it.

**PPM measurement rules:**
- **Ignore the first ~60 seconds** of a run entirely — TDS readings are erratic during startup
- **Ignore readings while diverting overboard** (`toggle_tank` == `1`) — these are pre-fill readings, not representative of production quality
- **Start collecting PPM stats only after `toggle_tank` transitions from `1` to `0`** (water starts going to tank) — this is the "stabilized" quality
- Track `min_ppm`, `max_ppm`, `avg_ppm` from the stabilized fill period only

**Time to fill**: Track `time_to_fill_seconds` — elapsed time from run start until `toggle_tank` first transitions to `0`. This metric trends upward as membranes age or prefilters degrade, making it a useful long-term health indicator.

#### Per-Run Data Collected

| Field | Source | Notes |
|-------|--------|-------|
| `start_time` | Timestamp of running state entry | |
| `end_time` | Timestamp of running → flushing transition | |
| `duration_minutes` | Calculated from start/end | |
| `liters_produced` | Integrated from `p_flow` readings over time (~1/sec samples) | Only counted while `toggle_tank` == `0` |
| `time_to_fill_seconds` | Time from start until `toggle_tank` first becomes `0` | Membrane/filter health indicator |
| `min_ppm` | Min `sal_1` during fill phase | |
| `max_ppm` | Max `sal_1` during fill phase | |
| `avg_ppm` | Mean `sal_1` during fill phase | Primary quality metric |
| `avg_feed_pressure_psi` | Average of `feed_p` during run | |
| `avg_water_temp_f` | Average of `temp_1` during run | |
| `stop_reason` | `manual`, `timer`, `tank_full`, `error` | |

#### Last Run Sensors

Derived from the most recent entry in the history store, updated on each run completion:

| Entity | Value |
|--------|-------|
| `sensor.spectra_last_run_start` | Timestamp |
| `sensor.spectra_last_run_end` | Timestamp |
| `sensor.spectra_last_run_duration` | Duration |
| `sensor.spectra_last_run_liters` | Liters produced |
| `sensor.spectra_last_run_avg_ppm` | Average TDS during fill |
| `sensor.spectra_last_run_min_ppm` | Min TDS during fill |
| `sensor.spectra_last_run_max_ppm` | Max TDS during fill |
| `sensor.spectra_last_run_time_to_fill` | Seconds from start to tank fill |
| `sensor.spectra_last_run_stop_reason` | Why it stopped |

#### Storage

Use HA's `Store` helper (`homeassistant.helpers.storage.Store`) — a JSON file in `.storage/spectra_watermaker_history`. Keep last N runs (configurable, default 50). This:
- Survives restarts
- Is backed up with HA snapshots
- Doesn't pollute the state machine / recorder database with large attribute blobs
- Can be exposed via a service call (`spectra_watermaker.get_run_history`) for dashboards
- Enables long-term trend analysis: plot `avg_ppm` and `time_to_fill_seconds` over weeks/months to detect membrane degradation or filter replacement needs

**Daily production** (`sensor.spectra_total_liters_today`) uses HA's `utility_meter` pattern — the coordinator accumulates liters from flow readings and resets at midnight. Persisted via `RestoreEntity` so it survives restarts within the same day.

### Architecture Notes

- Single `async` coordinator managing both WebSocket connections
- Reconnect logic with exponential backoff (device may be powered off for days)
- Port 9001 for sensor data (simple, always same format)
- Port 9000 for state detection + command sending
- Config flow validates by attempting WebSocket connection (or ping if outlet is off)
- All commands go through a command queue with 1500ms spacing
- Boot prompt auto-dismissal runs as a background task after WebSocket connects
