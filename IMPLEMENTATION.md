# Spectra Watermaker Assistant — Implementation Guide

Quick-reference for resuming work on this integration. Read this to get full context without reading the code.

## Repository

- **GitHub**: https://github.com/tomerddd/ha-spectra-watermaker
- **Version**: 0.9.0
- **Target**: HACS custom integration (structured for future HA core migration)

## Architecture

```
custom_components/spectra_watermaker/
├── Protocol layer (standalone, no HA imports — future PyPI package):
│   ├── models.py      — dataclasses, enums
│   ├── client.py      — dual WebSocket client with reconnect()
│   └── protocol.py    — command sequences, state detection
│
├── HA integration layer:
│   ├── coordinator.py — the brain: state machine, run tracking, auto-stop,
│   │                    time polling, events, anomaly detection
│   ├── sensor.py      — 40+ sensors via EntityDescription
│   ├── binary_sensor.py — 3 binary sensors
│   ├── button.py      — 7 buttons (start, stop, flush, reset prefilter/charcoal/strainer)
│   ├── switch.py      — power switch (conditional, state-aware availability)
│   ├── select.py      — water destination
│   ├── number.py      — run duration (1-5hrs, 0.25 step), tank threshold
│   ├── services.py    — 4 service handlers
│   ├── storage.py     — persistent storage (2 Store files)
│   ├── __init__.py    — setup/teardown
│   └── config_flow.py — 2-step config + full options flow
│
├── Config/metadata:
│   ├── const.py       — constants, model profiles, anomaly thresholds
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
    │                                  ├── _check_anomalies() (running phase)
    │                                  ├── _track_flush_data() (during flushing)
    │                                  ├── _check_anomalies() (flushing phase)
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
                                       ├── _handle_mid_run_prompt() (non-fatal warnings)
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
- `→ RUNNING`: starts run tracking, starts time polling, fires `run_started` event
- `RUNNING → FLUSHING`: ends run tracking, fires `run_completed` event, resets flush tracking, resets anomaly set
- `RUNNING → IDLE`: ends run tracking (abnormal — flush skipped)
- `RUNNING → PROMPT`: error check — if page 43 or "salinity"/"warning" in label, fires `run_error` event and dismisses; otherwise device_reboot
- `RUNNING → BOOTING`: device_reboot stop reason
- `RUNNING → anything else`: error stop reason
- `FLUSHING → IDLE`: stops time polling, records flush, checks end-of-flush TDS, starts auto-off timer
- `→ IDLE/PROMPT`: starts auto-off timer if not already running (catch-all for missed transitions)
- `BOOTING → PROMPT`: auto-dismiss boot prompts
- External start detection: running without integration commanding → tracks run

**Startup behavior**: On HA start, if the power switch entity is unavailable/unknown (common during boot when Zigbee hasn't loaded), the coordinator defaults to connecting rather than assuming off. Only skips connection if outlet is definitively `"off"`.

## Events System

Single event type `spectra_watermaker_event` with a `type` field. All events include current tank levels (`tank_port_pct`, `tank_stbd_pct`).

| Type | When | Key Data |
|------|------|----------|
| `run_started` | RUNNING entered | `duration_hours`, tank levels at start |
| `run_completed` | RUNNING→FLUSHING | `duration_minutes`, `liters_produced`, `stop_reason`, tanks before/after |
| `run_error` | Fatal error (salinity, etc.) | `error_page`, `error_message`, `duration_minutes` |
| `warning` | Non-fatal prompt mid-run, auto-dismissed | `page`, `message` |
| `anomaly` | Sensor out of bounds | `metric`, `value`, `expected_min`, `expected_max`, `possible_causes`, `phase` |
| `prompt_dismissed` | Boot prompt dismissed | `page`, `message` |
| `power_off` | Auto power-off fires | `reason` |

**Helper**: `_fire_event()` adds tank levels automatically and logs.

## Anomaly Detection

### Model-based thresholds
`const.py` → `get_model_profile(device_name)` returns thresholds based on the device field from port 9001. Supported models: Newport 1000/700/400, Ventura 150/200, Catalina. Conservative fallback for unknown models.

### Running phase checks (skip first 2 min)
| Metric | Field | Min | Max | Source |
|--------|-------|-----|-----|--------|
| Feed pressure | `feed_pressure_psi` | 100 | {pressure_limit} | Spectra programming guide |
| Boost pressure | `boost_pressure_psi` | 10 | {pressure_limit} | Spectra support |
| Product flow | `product_flow_gph` | {prod*0.5} | {prod*1.3} | Spectra spec sheet |
| Product TDS | `product_tds_ppm` | — | 500 | Spectra: 748 PPM reject threshold |
| Battery voltage | `battery_voltage` | 22.0 | — | — |
| Water temp | `water_temp_f` | 36 | 110 | Spectra operating range |

### Flushing phase checks
| Metric | Field | Min | Max |
|--------|-------|-----|-----|
| Feed pressure | `feed_pressure_psi` | 10 | 300 |
| Product flow | `product_flow_gph` | 10 | 80 |
| Battery voltage | `battery_voltage` | 22.0 | — |

### End-of-flush TDS check
Average of last 10 TDS samples checked against 1000 PPM (Spectra spec: should not taste salty).

### Dedup
`_fired_anomalies: set[str]` tracks which anomalies have fired. Reset on RUNNING→FLUSHING transition and on flush complete.

## Mid-Run Prompt Handling

In `_on_ui_message`, if a prompt page appears while RUNNING:
1. Page 43/14 + "salinity"/"warning" → skip (handled by `_handle_run_error` in state transition)
2. All others: log, fire `warning` event, auto-dismiss via BUTTON0, run continues

## Flush Data Tracking

During FLUSHING state, `_track_flush_data()` collects:
- `_flush_tds_samples` — product TDS
- `_flush_pressure_samples` — feed pressure
- `_flush_flow_samples` — product flow

On `_on_flush_complete()`: log summary (avg pressure, TDS start→end), check end-of-flush TDS, then reset.

## Maintenance Tracking

Three maintenance items, all following the same pattern (persistent in storage):

| Item | Storage fields | Sensors | Reset button |
|------|---------------|---------|-------------|
| Prefilter | `prefilter_last_changed`, `prefilter_hours` | days ago, hours since change | `reset_prefilter` |
| Charcoal filter | `charcoal_last_changed`, `charcoal_hours` | days ago, hours since change | `reset_charcoal` |
| Raw water strainer | `strainer_last_changed`, `strainer_hours` | days since cleaning, hours since cleaning | `reset_strainer` |

All three accumulate production hours in `_end_run_tracking()`. Reset buttons set timestamp to now and hours to 0. Dashboard reset buttons have confirmation dialogs.

## Button & Switch Availability

Buttons and power switch are state-aware:

| Entity | Available when |
|--------|---------------|
| Start | off, idle, prompt, error, booting |
| Stop | running, flushing |
| Flush | idle, prompt |
| Reset buttons | always |
| Power switch | off, idle, prompt, error, booting (disabled during running/flushing/starting) |

Buttons and switch subscribe to coordinator updates to reflect state changes immediately.

## Power Management

### Start from OFF
1. Turn on outlet switch
2. `client.reconnect()` — kills old WS tasks (which may have stale backoff) and starts fresh
3. Wait up to 60s for UI WebSocket
4. Dismiss boot prompts
5. Execute start sequence

### Auto power-off
- Triggered on any transition to IDLE or PROMPT (catch-all, not just after flush)
- Fires after `auto_off_minutes` (default 5)
- Checks state is still IDLE/OFF/PROMPT before powering off
- Fires `power_off` event
- Cancelled by: new start command or manual power-off

### Error recovery
- `async_start_watermaker` recovers from ERROR state if outlet is confirmed off
- Power switch shows "off" for OFF, ERROR, and BOOTING states

## Incremental Liters Saving

During a run, `_run_liters` is saved to `total_liters` in storage every 60 seconds. On run end, only the unsaved delta is added to avoid double-counting. Prevents data loss on crash/disconnect/manual stop.

## Page Field Mapping (confirmed by live testing)

| Page | Remaining Time | Elapsed Time | Other |
|------|---------------|-------------|-------|
| 5 (Product) | `label5` ("43m") | **not available** | `label8` = "Tank --" |
| 6 (Pressure) | `label5` ("43m") | **not available** | `label8` = "Tank --" |
| 30 (Prefilter) | **not available** | `label1` ("1h 3m"), confirmed by `label2` | |
| 31 (System Data) | **not available** | `label8` ("1h 3m"), confirmed by `label9` | |
| 32 (Main Dashboard) | **not available** | **not available** | Gauges only |

**Time polling**: `_poll_time_loop()` navigates right through pages every 15s while running/flushing.

## Config Flow

### Step 1: IP Address
- Validates by connecting to port 9001 WebSocket
- Reads `device` field from first message (e.g., "NEWPORT 1000")

### Step 2: Options
- Entity selectors for power switch, power sensor, port/stbd tank sensors
- Number selector for tank full threshold (50-100%, slider)

### Options Flow
- All initial config fields + auto_off_delay
- Updates `entry.data` for config fields, `entry.options` for auto_off_delay
- Triggers full reload on change

## Persistent Storage

### `spectra_watermaker_data_{entry_id}`
```json
{
  "prefilter_last_changed": "2026-04-18T12:00:00+00:00",
  "prefilter_hours": 45.2,
  "charcoal_last_changed": "2026-04-15T10:00:00+00:00",
  "charcoal_hours": 45.2,
  "strainer_last_changed": "2026-04-10T08:00:00+00:00",
  "strainer_hours": 45.2,
  "last_flush": "2026-04-19T15:44:38+00:00",
  "total_liters": 1250.5,
  "total_hours": 28.3,
  "run_duration": 2.0,
  "tank_full_threshold": 98.0
}
```

## Bugs Fixed

| Version | Issue | Fix |
|---------|-------|-----|
| 0.2.1 | Entity names truncated | Shortened device name to "Watermaker" |
| 0.2.2 | Elapsed/remaining time unknown | Added periodic page polling |
| 0.2.4 | Sensors blank after HA restart | Default to connecting when outlet entity not loaded |
| 0.2.5 | Elapsed time showed "Tank --" | Fixed field mapping per page |
| 0.2.6 | TDS showed 2440ppm when idle | Sensors return None when not running |
| 0.2.9 | No live run liters sensor | Added `current_run_liters` |
| 0.2.10 | Liters lost on crash/disconnect | Incremental save every 60s |
| 0.2.11 | Start from OFF fails (WS backoff) | Added `client.reconnect()`, extended wait to 60s |
| 0.2.12 | Power switch shows "on" during ERROR | Added ERROR and BOOTING to `is_on` exclusion |
| 0.2.13 | Auto power-off missed after HA restart | Auto-off on any IDLE/PROMPT transition |
| 0.9.0 | Events, anomaly detection, flush monitoring, maintenance tracking, button availability |

## Known Limitations

1. **Page 12 input fragility**: Setting duration via text input can disrupt WebSocket. Fallback uses last-used value.
2. **Single WS client**: Spectra may only support 1-2 concurrent connections. Web UI iframe may cause issues.
3. **toggle_tank visibility**: Only reported on running pages.
4. **f_flow always 0**: Feed flow sensor doesn't work on Newport 1000.
5. **Liters are estimates**: Integrated from ~1/sec flow samples.
6. **No run extension**: Can't extend mid-production. Must stop + restart.
7. **Mid-run HA restart**: Run tracking picks up from reconnect. Data before restart is lost.
8. **Time polling changes display**: 15s page navigation visible on touchscreen.
9. **Anomaly thresholds are fixed**: No user-configurable override (uses model auto-detect only).

## File Quick Reference

| Need to change... | Edit this file |
|-------------------|---------------|
| WebSocket protocol / parsing | `client.py` |
| Command sequences (start/stop/flush) | `protocol.py` |
| State machine logic | `coordinator.py` → `_handle_state_transition()` |
| Events / anomaly detection | `coordinator.py` → `_fire_event()`, `_check_anomalies()` |
| Run error handling | `coordinator.py` → `_handle_run_error()` |
| Mid-run prompt handling | `coordinator.py` → `_handle_mid_run_prompt()` |
| Run tracking / PPM rules | `coordinator.py` → `_track_run_data()`, `_handle_toggle_change()` |
| Flush data tracking | `coordinator.py` → `_track_flush_data()`, `_on_flush_complete()` |
| Model profiles / thresholds | `const.py` → `get_model_profile()`, `_RUNNING_CHECKS_TEMPLATE` |
| Sensor visibility | `sensor.py` → `value_fn` lambdas |
| Add/modify a sensor | `sensor.py` (add to SENSOR_DESCRIPTIONS tuple) |
| Maintenance tracking | `storage.py` (properties), `sensor.py` (sensors), `button.py` (reset) |
| Button availability | `button.py` → `available` property |
| Power switch behavior | `switch.py` → `is_on`, `available` |
| Persistent data fields | `storage.py` |
| Config flow options | `config_flow.py` |
| Service handlers | `services.py` + `services.yaml` |
| Constants / thresholds | `const.py` |
| UI text / translations | `strings.json` + `translations/en.json` |
