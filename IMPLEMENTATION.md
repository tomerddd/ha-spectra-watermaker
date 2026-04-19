# Spectra Watermaker Assistant — Implementation Guide

Quick-reference for resuming work on this integration. Read this to get full context without reading 3,500 lines of code.

## Repository

- **GitHub**: https://github.com/tomerddd/ha-spectra-watermaker
- **Version**: 0.2.0
- **Total code**: ~3,500 lines across 15 Python files + 1 YAML
- **Target**: HACS custom integration (structured for future HA core migration)

## Architecture

```
custom_components/spectra_watermaker/
├── Protocol layer (standalone, no HA imports — future PyPI package):
│   ├── models.py      (237 lines) — dataclasses, enums
│   ├── client.py      (360 lines) — dual WebSocket client
│   └── protocol.py    (450 lines) — command sequences, state detection
│
├── HA integration layer:
│   ├── coordinator.py (965 lines) — the brain: state machine, run tracking, auto-stop
│   ├── sensor.py      (405 lines) — 30 sensors via EntityDescription
│   ├── binary_sensor.py (110 lines) — 3 binary sensors
│   ├── button.py      (100 lines) — 4 buttons
│   ├── switch.py       (83 lines) — power switch (conditional)
│   ├── select.py       (71 lines) — water destination
│   ├── number.py      (123 lines) — run duration, tank threshold
│   ├── services.py    (113 lines) — 4 service handlers
│   ├── storage.py     (163 lines) — persistent storage (2 Store files)
│   ├── __init__.py     (62 lines) — setup/teardown
│   └── config_flow.py (197 lines) — 2-step config + options flow
│
├── Config/metadata:
│   ├── const.py        (74 lines)
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
- `→ RUNNING`: starts run tracking (_start_run_tracking)
- `RUNNING → FLUSHING`: ends run tracking, saves RunRecord to history
- `RUNNING → IDLE`: ends run tracking (abnormal — flush skipped)
- `FLUSHING → IDLE`: records flush timestamp, starts auto-off timer
- `BOOTING → PROMPT`: auto-dismiss boot prompts
- `RUNNING → BOOTING/PROMPT`: device_reboot stop reason
- External start detection: running without integration commanding → skip auto-off

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
`_find_button_by_label()` scans button0-button3 labels for a case-insensitive match. This makes the integration model-independent — different Spectra models may have buttons in different positions.

## Run Tracking

### What's tracked per run (coordinator._track_run_data, called ~1/sec):

| Metric | How | Conditions |
|--------|-----|------------|
| Liters | `product_flow_lph / 3600` accumulated | Only while `toggle_tank == "0"` (tank) |
| PPM samples | `product_tds_ppm` appended to list | After 60s startup ignore AND 30s post-toggle delay AND `toggle_tank == "0"` |
| Pressure samples | `feed_pressure_psi` appended | Always (if > 0) |
| Temp samples | `water_temp_f` appended | Always (if > 32.1, filters disconnected sensor) |
| Time to fill | `monotonic() - run_start` when toggle first goes 1→0 | First toggle transition only |

### PPM collection rules (important for data quality):

1. **Ignore first 60 seconds** of run entirely — TDS erratic during startup
2. **Only collect while `toggle_tank == "0"`** — overboard water is pre-fill quality
3. **30-second post-toggle delay** — when toggle changes 1→0, water in pipes is still old quality
4. **Edge case**: if toggle starts at "0" (rare), `_filling_started = True` immediately, PPM collection scheduled via `call_later(60s)` (Issue #9 fix)

### Run record storage:
- `RunRecord` dataclass with 12 fields (models.py)
- Stored in `.storage/spectra_watermaker_history_{entry_id}` as JSON
- Last 50 runs kept (configurable via DEFAULT_HISTORY_LIMIT)
- Exposed via `spectra_watermaker.get_run_history` service

## Persistent Storage

Two `Store` files in `.storage/`:

### `spectra_watermaker_data_{entry_id}`
```json
{
  "prefilter_last_changed": "2026-04-18T12:00:00+00:00",
  "prefilter_hours": 45.2,
  "last_flush": "2026-04-18T14:38:41+00:00",
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
      "start_time": "2026-04-18T13:00:00+00:00",
      "end_time": "2026-04-18T14:30:00+00:00",
      "duration_minutes": 90.0,
      "liters_produced": 270.5,
      "time_to_fill_seconds": 120,
      "min_ppm": 285.0, "max_ppm": 315.0, "avg_ppm": 298.5,
      "avg_feed_pressure_psi": 194.5,
      "avg_water_temp_f": 82.4,
      "stop_reason": "timer",
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
- Shared `device_info` dict grouping all entities under one device
- Subscribe to coordinator updates via `async_add_listener`

### Sensors (sensor.py)
- 30 sensors defined as `SpectraSensorDescription` dataclasses
- Each has a `value_fn: Callable[[SpectraCoordinator], Any]` lambda
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

## Review Issues Fixed

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

## Testing Checklist (for live testing)

- [ ] Config flow: add integration with watermaker IP
- [ ] Config flow: add with power switch + tank sensors
- [ ] Sensors populate when watermaker is idle
- [ ] Start button: powers on, dismisses prompts, starts production
- [ ] Sensors update ~1/sec during production
- [ ] Water quality shows correct level for TDS range
- [ ] Stop button: stops production, enters flush
- [ ] Flush progress shows 0→100%
- [ ] Flush complete: last_flush timestamp updates, auto-off timer starts
- [ ] Auto power-off fires after configured delay
- [ ] Tank full auto-stop: debounce works, stop fires after 30s sustained
- [ ] Run history: service returns correct data
- [ ] Prefilter reset: timestamp and hours both reset
- [ ] Total liters: only counts while filling tank (not overboard)
- [ ] HA restart: totals, prefilter, history survive restart
- [ ] Power cycle: boot prompt auto-dismissed, reaches idle
- [ ] External start (from touchscreen): detected, tracked, no auto-off
- [ ] Both WS down: error state after 30s
- [ ] Energy dashboard: total_liters shows up as water consumption

## File Quick Reference

| Need to change... | Edit this file |
|-------------------|---------------|
| WebSocket protocol / parsing | `client.py` |
| Command sequences (start/stop/flush) | `protocol.py` |
| State machine logic | `coordinator.py` (lines 559-623) |
| Run tracking / PPM rules | `coordinator.py` (lines 624-781) |
| Tank auto-stop | `coordinator.py` (lines 838-910) |
| Auto power-off | `coordinator.py` (lines 912-940) |
| Add/modify a sensor | `sensor.py` (add to SENSOR_DESCRIPTIONS tuple) |
| Add/modify a binary sensor | `binary_sensor.py` |
| Persistent data fields | `storage.py` |
| Config flow options | `config_flow.py` |
| Service handlers | `services.py` + `services.yaml` |
| Constants / thresholds | `const.py` |
| UI text / translations | `strings.json` + `translations/en.json` |
