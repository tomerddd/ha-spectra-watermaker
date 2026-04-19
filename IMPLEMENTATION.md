# Spectra Watermaker Assistant — Implementation Guide

Quick-reference for resuming work on this integration. Read this to get full context without reading ~3,600 lines of code.

## Repository

- **GitHub**: https://github.com/tomerddd/ha-spectra-watermaker
- **Version**: 0.2.6
- **Total code**: ~3,600 lines across 15 Python files + 1 YAML
- **Target**: HACS custom integration (structured for future HA core migration)

## Architecture

```
custom_components/spectra_watermaker/
├── Protocol layer (standalone, no HA imports — future PyPI package):
│   ├── models.py      — dataclasses, enums
│   ├── client.py      — dual WebSocket client
│   └── protocol.py    — command sequences, state detection
│
├── HA integration layer:
│   ├── coordinator.py — the brain: state machine, run tracking, auto-stop, time polling
│   ├── sensor.py      — 31 sensors via EntityDescription
│   ├── binary_sensor.py — 3 binary sensors
│   ├── button.py      — 4 buttons
│   ├── switch.py      — power switch (conditional)
│   ├── select.py      — water destination
│   ├── number.py      — run duration, tank threshold
│   ├── services.py    — 4 service handlers
│   ├── storage.py     — persistent storage (2 Store files)
│   ├── __init__.py    — setup/teardown
│   └── config_flow.py — 2-step config + options flow
│
├── Config/metadata:
│   ├── const.py
│   ├── manifest.json
│   ├── strings.json / translations/en.json
│   └── services.yaml
```

## Data Flow

```
Spectra Watermaker (192.168.50.25)
    │
    ├── Port 9001 (data) ──→ SpectraClient._handle_data_message()
    │   JSON ~1/sec              │
    │   {p_flow, feed_p,         ├──→ SpectraData dataclass (with unit conversions)
    │    sal_1, temp_1, ...}     │
    │                            └──→ coordinator._on_data_message()
    │                                  ├── detect_state() (ground truth: is_running)
    │                                  ├── _track_run_data() (liters, PPM, pressure)
    │                                  └── async_set_updated_data() → entity updates
    │
    └── Port 9000 (UI) ───→ SpectraClient._handle_ui_message()
        JSON ~1/sec              │
        {page, label0,           ├──→ SpectraUIState dataclass
         button0, gauge0,        │
         toggle_tank, ...}       └──→ coordinator._on_ui_message()
                                       ├── protocol.update_ui_state()
                                       ├── _extract_ui_data() (times, filter, flush)
                                       ├── _handle_toggle_change() (tank/overboard)
                                       ├── detect_state() (page-based details)
                                       └── async_set_updated_data() → entity updates
```

## State Machine

```
OFF ──power_on──→ BOOTING ──ws_connects──→ PROMPT ──auto_dismiss──→ IDLE
 ↑                                                                    │
 │                                                                   start
 │                                                                    │
 │                                                                    ↓
 └──auto_off(5min)──← IDLE ←──flush_done──← FLUSHING ←──stop──← RUNNING
```

**State detection priority** (coordinator.py → protocol.detect_state()):
1. Port 9001 `is_running` (p_flow > 0.5 AND feed_p > 100) = ground truth for RUNNING
2. Port 9000 page 2 = FLUSHING
3. Port 9000 label0 contains "AUTORUN" = RUNNING, "FLUSH" = FLUSHING
4. Port 9000 running pages (5,6,30,31,32) = RUNNING
5. Port 9000 idle pages (4,37,39,40,48,49) = IDLE
6. Port 9000 page 10/101 = PROMPT/BOOTING
7. If someone is browsing settings → falls through to IDLE (correct behavior)

**Key transitions and side effects** (coordinator._handle_state_transition()):
- `→ RUNNING`: starts run tracking (_start_run_tracking), starts time polling
- `RUNNING → FLUSHING`: ends run tracking, saves RunRecord to history
- `RUNNING → IDLE`: ends run tracking (abnormal — flush skipped)
- `FLUSHING → IDLE`: stops time polling, records flush timestamp, starts auto-off timer
- `BOOTING → PROMPT`: auto-dismiss boot prompts
- `RUNNING → BOOTING/PROMPT`: device_reboot stop reason
- External start detection: running without integration commanding → skip auto-off

**Startup behavior**: On HA start, if the power switch entity is unavailable/unknown (common during boot when Zigbee hasn't loaded), the coordinator defaults to connecting rather than assuming off. Only skips connection if outlet is definitively `"off"`.

## Page Field Mapping (confirmed by live testing)

Elapsed and remaining time are on **different pages**:

| Page | Remaining Time | Elapsed Time | Other |
|------|---------------|-------------|-------|
| 5 (Product) | `label5` ("43m") | **not available** | `label8` = "Tank --" (tank level, NOT time) |
| 6 (Pressure) | `label5` ("43m") | **not available** | `label8` = "Tank --" |
| 30 (Prefilter) | **not available** | `label1` ("1h 3m"), confirmed by `label2` = "Elapsed time" | |
| 31 (System Data) | **not available** | `label8` ("1h 3m"), confirmed by `label9` = "Elapsed time" | All sensor data as text |
| 32 (Main Dashboard) | **not available** | **not available** | Gauges only |

**Time polling**: `_poll_time_loop()` navigates right through pages every 15s while running/flushing to capture both remaining (pages 5/6) and elapsed (pages 30/31). Started on RUNNING entry, stopped on FLUSHING→IDLE.

## Sensor Value Visibility

Sensors from port 9001 show different behavior based on state:

| Sensor | When shown | Why |
|--------|-----------|-----|
| product_flow, boost_pressure, feed_pressure | Only while `is_running` | Idle residual values are confusing (3-5 psi noise) |
| product_tds | Only while `is_running` | Stale membrane reading shows ~2400 ppm when idle |
| water_temperature | Only while `is_running` AND `temp_f > 33` | Disconnected sensor default is 32°F |
| battery_voltage | Always (when connected) | Valid reading regardless of state |
| feed_flow, feed_tds | Always (when connected) | Diagnostic, always valid |
| water_quality | Only while `is_running` | Derived from TDS |

## Run Progress Sensor

`sensor.spectra_watermaker_run_progress` — a single 0-100% value representing the full cycle:

- **0-92%**: Production phase. Calculated as `elapsed / (elapsed + remaining) * 92.0` using Spectra's own timer values (parsed from time strings like "1h 20m").
- **92-100%**: Flush phase. Calculated as `92.0 + (flush_gauge / 100.0 * 8.0)` from the Spectra's flush progress gauge on page 2.
- **None**: When idle/off.

The 92/8 split approximates a typical 1hr run + 7min flush. A dashboard progress bar uses severity bands: green (running), yellow >85% (almost done), red >92% (flushing).

Time string parser `_parse_time_to_minutes()` handles: "1h 20m"→80, "45m"→45, "2h"→120.

## Command Sequences

### Start (protocol._execute_start)
```
Page 10 BUTTON0       # Dismiss screensaver (if needed)
Page 4  BUTTON1*      # START (*found by label text, fallback BUTTON1)
Page 37 BUTTON0*      # AUTORUN (*found by label text)
Page 29 BUTTON2       # Select "hours"
Page 29 LABEL0        # Open input → page 12
Page 12 data:"1.5"    # Set duration
  → back to page 29
Page 29 BUTTON3       # OK
  → Page 10 countdown (8s) → Page 32 RUNNING
```

Each step verifies the expected page appeared within 5 seconds. If not, rollback (_try_rollback: BUTTON4 back, then CANCEL).

**Page 12 fallback**: If page 12 never appears after LABEL0 (known fragility), logs warning and presses OK with Spectra's last-used duration.

### Stop
Single command: `BUTTON0` on current running/flushing page. Only accepted from pages {2, 5, 6, 30, 31, 32}.

### Flush
Dismiss screensaver if needed, then `BUTTON0` on idle page 4 (found by label "FLUSH").

### Button detection
`_find_button_by_label()` scans button0-button3 labels for a case-insensitive match. This makes the integration model-independent.

## Run Tracking

### What's tracked per run (coordinator._track_run_data, called ~1/sec):

| Metric | How | Conditions |
|--------|-----|------------|
| Liters | `product_flow_lph / 3600` accumulated | Only while `toggle_tank == "0"` (tank) |
| PPM samples | `product_tds_ppm` appended to list | After 60s startup ignore AND 30s post-toggle delay AND `toggle_tank == "0"` |
| Pressure samples | `feed_pressure_psi` appended | Always (if > 0) |
| Temp samples | `water_temp_f` appended | Always (if > 32.1, filters disconnected sensor) |
| Time to fill | `monotonic() - run_start` when toggle first goes 1→0 | First toggle transition only |

### PPM collection rules:

1. **Ignore first 60 seconds** of run entirely — TDS erratic during startup
2. **Only collect while `toggle_tank == "0"`** — overboard water is pre-fill quality
3. **30-second post-toggle delay** — when toggle changes 1→0, water in pipes is still old quality
4. **Edge case**: if toggle starts at "0" (rare), `_filling_started = True` immediately, PPM collection scheduled via `call_later(60s)`

### Run record storage:
- `RunRecord` dataclass with 12 fields (models.py)
- Stored in `.storage/spectra_watermaker_history_{entry_id}` as JSON
- Last 50 runs kept (configurable via DEFAULT_HISTORY_LIMIT)
- Exposed via `spectra_watermaker.get_run_history` service

### Mid-run HA restart:
If HA restarts while the watermaker is running, the coordinator detects running state on reconnect and starts tracking from that point. The RunRecord will have `data_incomplete: true`, and liters/PPM/hours will only reflect the portion tracked after reconnect. The run before the restart is lost.

## Persistent Storage

Two `Store` files in `.storage/`:

### `spectra_watermaker_data_{entry_id}`
```json
{
  "prefilter_last_changed": "2026-04-18T12:00:00+00:00",
  "prefilter_hours": 45.2,
  "last_flush": "2026-04-19T15:44:38+00:00",
  "total_liters": 1250.5,
  "total_hours": 28.3,
  "run_duration": 2.0,
  "tank_full_threshold": 98.0
}
```

### `spectra_watermaker_history_{entry_id}`
```json
{
  "runs": [
    {
      "start_time": "2026-04-19T14:30:00+00:00",
      "end_time": "2026-04-19T15:36:43+00:00",
      "duration_minutes": 66.7,
      "liters_produced": 180.5,
      "time_to_fill_seconds": 120,
      "min_ppm": 285.0, "max_ppm": 315.0, "avg_ppm": 298.5,
      "avg_feed_pressure_psi": 194.5,
      "avg_water_temp_f": 82.4,
      "stop_reason": "manual",
      "data_incomplete": false
    }
  ]
}
```

## WebSocket Client (client.py)

### Connection management
- Two independent connection loops (`_run_connection`), one per port
- Exponential backoff: 1s → 2s → 4s → ... → 60s max. Reset on successful connect.
- Heartbeat: if no port 9001 message for 5 seconds, force-close and reconnect
- All three tasks (data, UI, heartbeat) created via `asyncio.create_task`

### Command spacing
- `asyncio.Lock` ensures one command at a time
- 1500ms minimum delay between commands (enforced in `send_command` and `send_data`)
- Measured via `time.monotonic()`

### Parsing
- Port 9001: `"47.95 gph"` → `float(value.split()[0])` → `47.95`
- Port 9000: raw JSON fields mapped directly to `SpectraUIState` dataclass
- Unit conversions: gph→L/h (×3.78541), °F→°C ((F-32)×5/9) — computed properties on `SpectraData`

## Tank Full Auto-Stop

1. `_subscribe_tanks()` registers `async_track_state_change_event` for configured tank entities
2. `_on_tank_state_change()` fires on any tank level change
3. If level ≥ threshold AND state is RUNNING → start 30s debounce timer (`call_later`)
4. If level drops below threshold before 30s → cancel timer
5. After 30s sustained: fire `spectra_watermaker_tank_full_stop` event, call `async_stop_watermaker(TANK_FULL)`
6. Only active while RUNNING — timer cancelled on any non-running state

## Auto Power-Off

1. Triggered when FLUSHING → IDLE transition occurs AND `_integration_powered_on` is True
2. `call_later(auto_off_minutes * 60)` schedules `_auto_off_fire`
3. `_auto_off_fire` checks state is still IDLE, then calls `async_power_off()`
4. Timer cancelled if: new start command, manual power-off, or state changes
5. NOT triggered if watermaker was started externally (from physical touchscreen)

## Boot Prompt Handling (protocol.dismiss_prompts)

Up to 10 attempts, 2 seconds apart:
- **Page 101**: wait (system initializing)
- **Page 10 "POWER INTERRUPT"**: BUTTON0 (OK)
- **Page 10 "AUTOSTORE"**: BUTTON0 (dismiss screensaver)
- **Page 10 "starting"**: wait (countdown)
- **Pages 1/44/45 with "chemical"/"stored"**: find "No" button by label, fallback BUTTON1
- **Any other**: BUTTON0
- **Idle page reached**: return True

## Entity Design Patterns

All entities follow the same pattern:
- `_attr_has_entity_name = True` (uses device name as prefix)
- `_attr_translation_key` for localized names
- `_attr_unique_id = f"{entry_id}_{key}"`
- Shared `device_info` dict grouping all entities under one device (name: "Watermaker")
- Subscribe to coordinator updates via `async_add_listener`

### Sensors (sensor.py)
- 31 sensors defined as `SpectraSensorDescription` dataclasses
- Each has a `value_fn: Callable[[SpectraCoordinator], Any]` lambda
- Key sensors (flow, pressure, TDS, temp) return `None` when not running to avoid showing stale idle values
- Optional `attr_fn` for extra state attributes
- `_days_since()` helper for prefilter/flush age calculations
- Diagnostic entities: `entity_category=EntityCategory.DIAGNOSTIC` (hidden by default)

### Conditional entities
- `switch.spectra_power`: only created if `CONF_POWER_SWITCH` is configured
- `number.spectra_tank_full_threshold`: only created if tank sensors are configured

## Config Flow

### Step 1: IP Address
- Validates by connecting to port 9001 WebSocket
- Reads `device` field from first message (e.g., "NEWPORT 1000")
- Rejects duplicates via `_async_abort_entries_match`

### Step 2: Options
- Entity selectors for power switch, power sensor, port/stbd tank sensors
- Number selector for tank full threshold (50-100%, slider)
- All optional

### Options Flow
- Currently only exposes `auto_off_delay` (minutes, slider 0-60)
- Triggers full reload on change

## Bugs Fixed (post-initial release)

| Version | Issue | Fix |
|---------|-------|-----|
| 0.2.1 | Entity names truncated ("Spectra NEWPORT 1000 Product...") | Shortened device name to "Watermaker" |
| 0.2.2 | Elapsed/remaining time always unknown | Added periodic page polling (navigate through running pages) |
| 0.2.4 | Sensors blank after HA restart | Fixed startup: connect WS when outlet entity not yet loaded (default to connecting instead of assuming off) |
| 0.2.5 | Elapsed time showed "Tank --" | Fixed field mapping: elapsed on pages 30/31, remaining on pages 5/6 (different pages). Poll every 15s through all pages. |
| 0.2.6 | TDS showed 2440ppm, temp 0°C when idle | Sensors now return None when not running (stale membrane/sensor readings hidden) |

## Review Issues Fixed (initial code review)

| # | Issue | Fix |
|---|-------|-----|
| 1 | `SensorDeviceClass.WATER` with L/h unit | Changed to `VOLUME_FLOW_RATE` with `LITERS_PER_HOUR` |
| 2 | Deprecated `asyncio.get_event_loop()` | Replaced with `get_running_loop()` |
| 4 | Both-down timeout never fires proactively | Added `call_later` when `_both_down_since` is first set |
| 8 | `CONF_POWER_SENSOR` never used | Added comment: reserved for future power-based state fallback |
| 9 | PPM never collected if toggle starts at "0" | Check toggle at run start, schedule PPM via `call_later(60s)` |
| 12 | `_auto_off_minutes` type mismatch | Cast to `int()` |
| 13/17 | Number values not persisted | Added to `SpectraStorage`, loaded on start, saved on change |
| 18 | Bare `except Exception` in config flow | Narrowed to specific exceptions |

## Known Limitations

1. **Page 12 input fragility**: Setting duration via the Spectra's text input page can disrupt WebSocket. Fallback uses last-used value.
2. **Single WS client**: Spectra may only support 1-2 concurrent WebSocket connections. Having the web UI open simultaneously may cause issues.
3. **toggle_tank visibility**: Only reported on running pages. If someone navigates to settings during a run, toggle transitions may be missed.
4. **f_flow always 0**: Feed flow sensor doesn't work on Newport 1000. Marked diagnostic.
5. **Liters are estimates**: Integrated from ~1/sec flow samples. Gaps from reconnections cause undercounting.
6. **No run extension**: Can't extend a run mid-production. Must stop (8min flush) and restart.
7. **CONF_POWER_SENSOR**: Collected in config but not yet used. Reserved for future power-based state detection.
8. **Mid-run HA restart**: Run tracking picks up from reconnect moment. Liters/PPM/hours before the restart are lost. RunRecord gets `data_incomplete: true`.
9. **Time polling changes the physical display**: The 15s page navigation is visible on the Spectra's touchscreen. Not harmful but may be surprising if someone is looking at it.

## Testing Checklist

- [x] Config flow: add integration with watermaker IP
- [x] Config flow: add with power switch + tank sensors
- [ ] Sensors populate correctly when watermaker is idle (values hidden for running-only sensors)
- [ ] Start button: powers on, dismisses prompts, starts production
- [x] Sensors update ~1/sec during production
- [x] Water quality shows correct level for TDS range (showed "good" at ~300ppm)
- [x] Stop button: stops production, enters flush
- [ ] Flush progress shows 0→100%
- [x] Flush complete: last_flush timestamp updates
- [ ] Auto power-off fires after configured delay
- [ ] Tank full auto-stop: debounce works, stop fires after 30s sustained
- [ ] Run history: service returns correct data with full run
- [ ] Prefilter reset: timestamp and hours both reset
- [x] Total liters: only counts while filling tank (not overboard)
- [x] HA restart mid-run: reconnects, detects running state
- [x] Power cycle: boot prompt auto-dismissed (POWER INTERRUPT), reaches idle
- [ ] External start (from touchscreen): detected, tracked, no auto-off
- [ ] Both WS down: error state after 30s
- [ ] Energy dashboard: total_liters shows up as water consumption
- [x] Elapsed time reads from page 30/31 correctly
- [x] Remaining time reads from page 5/6 correctly
- [ ] Run progress bar shows 0-92% during run, 92-100% during flush

## File Quick Reference

| Need to change... | Edit this file |
|-------------------|---------------|
| WebSocket protocol / parsing | `client.py` |
| Command sequences (start/stop/flush) | `protocol.py` |
| State machine logic | `coordinator.py` → `_handle_state_transition()` |
| Run tracking / PPM rules | `coordinator.py` → `_track_run_data()`, `_handle_toggle_change()` |
| Time extraction from pages | `coordinator.py` → `_extract_ui_data()` |
| Time polling loop | `coordinator.py` → `_poll_time_loop()` |
| Tank auto-stop | `coordinator.py` → `_subscribe_tanks()`, `_on_tank_state_change()` |
| Auto power-off | `coordinator.py` → `_start_auto_off_timer()`, `_auto_off_fire()` |
| Sensor visibility (when to show/hide) | `sensor.py` → `value_fn` lambdas |
| Add/modify a sensor | `sensor.py` (add to SENSOR_DESCRIPTIONS tuple) |
| Add/modify a binary sensor | `binary_sensor.py` |
| Persistent data fields | `storage.py` |
| Config flow options | `config_flow.py` |
| Service handlers | `services.py` + `services.yaml` |
| Constants / thresholds | `const.py` |
| UI text / translations | `strings.json` + `translations/en.json` |
| Dashboard cards | `/var/lib/homeassistant/homeassistant/.storage/lovelace.dashboard_watermaker` (local, not in HACS) |
