# Spectra Watermaker Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/tomerddd/ha-spectra-watermaker.svg)](https://github.com/tomerddd/ha-spectra-watermaker/releases)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=tomerddd&repository=ha-spectra-watermaker&category=integration)

Home Assistant integration for **Spectra Watermakers** equipped with the [Spectra Connect](https://spectrawatermakers.com) module (built-in Ethernet on Newport 1000/400c, or external module on other models). Provides full monitoring and control via the watermaker's WebSocket interface — no cloud, no polling, pure local push.

Tested with the **Spectra Newport 1000**. Should work with other Spectra models using the Spectra Connect module (Newport 400c, Catalina, Ventura, etc.).

## Features

### Monitoring
- **Real-time sensor data** — product flow rate, feed/boost pressure, TDS (salinity), water temperature, battery voltage, filter condition
- **Run state tracking** — off, booting, idle, running, flushing, with detailed sub-states
- **Water destination** — filling tank vs. diverting overboard
- **Flush countdown** — remaining time during post-run freshwater flush
- **Elapsed & remaining time** — for timed runs
- **Live run liters** — real-time liters produced during the current run

### Control
- **Start / Stop** — fill tank, autofill (liters or hours), and stop via HA services or dashboard buttons
- **Water destination toggle** — switch between tank fill and overboard
- **Power management** — optional smart outlet integration to power on/off the watermaker, with automatic boot prompt dismissal
- **Tank full auto-stop** — connect your tank level sensors (any source) and set a threshold; the integration stops the watermaker when tanks are full (30s debounce to handle sloshing)
- **Salinity auto-retry** — if the watermaker stops due to high salinity on cold start, automatically dismisses the error, stops the flush, and retries once

### Anomaly Detection
- **Continuous sensor monitoring** during both running and flushing phases
- **Model-specific thresholds** auto-detected from the device name (Newport 1000/700/400, Ventura, Catalina)
- **Actionable diagnostics** — each anomaly includes possible causes sourced from Spectra documentation
- **Mid-run warning handling** — non-fatal prompts (filter reminders, pump hour counts) are auto-dismissed and reported

### Events & Notifications
- **HA events** fired for all lifecycle moments (start, complete, error, anomaly, power-off)
- **Easy automation** — listen to a single event type and route to your notification system
- **Tank level context** — every event includes current port/starboard tank percentages

### History & Maintenance
- **Run history** — logs each production run with duration, liters produced, min/max/avg TDS, stop reason, and time-to-fill
- **Flush data logging** — tracks pressure, flow, and TDS during flush cycles
- **Water quality trends** — tracks TDS and time-to-fill across runs to detect membrane degradation
- **Daily production total** — liters produced today, resets at midnight
- **Prefilter tracking** — records when prefilters were last changed, with days-ago counter and reset button

## Installation

### HACS (Recommended)

1. Open **HACS** in Home Assistant
2. Click the three-dot menu (top right) > **Custom repositories**
3. Add `https://github.com/tomerddd/ha-spectra-watermaker` with category **Integration**
4. Search for **Spectra Watermaker Assistant** and click **Download**
5. **Restart Home Assistant**

### Manual

1. Copy `custom_components/spectra_watermaker/` to your Home Assistant `custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings** > **Devices & Services**
2. Click **Add Integration** and search for **Spectra Watermaker Assistant**
3. Enter the IP address of your Spectra Connect module
4. (Optional) Configure:
   - **Power outlet switch** — a switch entity that controls power to the watermaker
   - **Power consumption sensor** — for secondary state detection (watts)
   - **Port/Starboard tank level sensors** — from any system (SignalK, Victron, etc.)
   - **Tank full threshold** — percentage at which to auto-stop (default: 98%)

## Events

The integration fires `spectra_watermaker_event` events for all key lifecycle moments. Each event contains a `type` field and current tank levels.

### Event Types

| Type | When | Key Data |
|------|------|----------|
| `run_started` | Watermaker begins producing | `duration_hours`, `tank_port_pct`, `tank_stbd_pct` |
| `run_completed` | Run finishes (enters flush) | `duration_minutes`, `liters_produced`, `stop_reason`, tank levels before and after |
| `run_error` | Fatal error stops run | `error_page`, `error_message`, `will_retry`, `duration_minutes` |
| `warning` | Non-fatal prompt auto-dismissed mid-run | `page`, `message` |
| `anomaly` | Sensor value out of bounds | `metric`, `value`, `expected_min`, `expected_max`, `possible_causes`, `phase` |
| `prompt_dismissed` | Boot prompt auto-dismissed | `page`, `message` |
| `power_off` | Auto power-off triggered | `reason` |

### Example Automation

```yaml
- alias: "Watermaker Notifications"
  triggers:
    - trigger: event
      event_type: spectra_watermaker_event
  actions:
    - variables:
        evt: "{{ trigger.event.data }}"
        type: "{{ evt.type }}"
    - choose:
        - conditions: "{{ type == 'run_started' }}"
          sequence:
            - action: notify.mobile_app
              data:
                title: "Watermaker Started"
                message: "Making water for {{ evt.duration_hours }}hrs"
        - conditions: "{{ type == 'run_completed' }}"
          sequence:
            - action: notify.mobile_app
              data:
                title: "Watermaker Done"
                message: "Made ~{{ evt.liters_produced | round(0) }}L in {{ evt.duration_minutes | round(0) }}min"
        - conditions: "{{ type == 'anomaly' }}"
          sequence:
            - action: notify.mobile_app
              data:
                title: "Watermaker Anomaly"
                message: "{{ evt.metric }}: {{ evt.value }}. Possible: {{ evt.possible_causes | join(', ') }}"
```

## Anomaly Detection

The integration continuously monitors sensor data during **running** and **flushing** phases. Thresholds are automatically selected based on the detected Spectra model. Each anomaly fires once per run/flush cycle to avoid notification spam.

Anomaly checks are skipped during the first 2 minutes of a run (startup settling period).

### Salinity Auto-Retry

On cold starts, the Spectra may stop with a "Salinity exceeds maximum limit" error before the membranes warm up. The integration handles this automatically:

1. Detects the salinity error (page 43)
2. Fires a `run_error` event with `will_retry: true`
3. Dismisses the error prompt
4. Stops the post-error flush
5. Restarts the watermaker with the same duration
6. If the retry also fails, fires `run_error` with `will_retry: false` and gives up

The retry counter resets after 5 minutes of successful running.

### Mid-Run Warnings

Non-fatal prompts that appear during a run (filter change reminders, pump hour counts) are:
1. Logged with full page content
2. Reported via a `warning` event
3. Auto-dismissed so the run continues uninterrupted

### Running Phase Thresholds

Values are model-specific. Example for **Newport 1000** (pressure limit: 250 PSI, production: 41 GPH):

| Metric | Min | Max | Low Causes | High Causes |
|--------|-----|-----|------------|-------------|
| Feed pressure | 100 PSI | 250 PSI | Clogged prefilter; feed pump issue; air leak in intake; low boost pump voltage | Membrane fouling/scaling — needs chemical cleaning; restriction in brine discharge |
| Boost pressure | 10 PSI | 250 PSI | Boost pump failing; low voltage (need ≥90% source); clogged prefilter | Restriction downstream of boost pump |
| Product flow | 20 GPH | 53 GPH | Membrane fouling; low pressure; cold water (-50% at 48°F); aged membrane | O-ring failure; brine seal misaligned; sensor issue |
| Product TDS | — | 500 PPM | — | Membrane aging (replace at 700-800); O-ring leak; brine seal; membrane bypass |
| Battery voltage | 22.0 V | — | Insufficient charging; high load; battery issue | — |
| Water temperature | 36°F | 110°F | Cold water reduces output (per Spectra: -50% at 48°F) | Above operating range; sensor issue |

### Flushing Phase Thresholds

| Metric | Min | Max | Low Causes | High Causes |
|--------|-----|-----|------------|-------------|
| Feed pressure | 10 PSI | 300 PSI | Flush pump not running; flush valve not opening | High-pressure pump not disengaged; valve issue |
| Product flow | 10 GPH | 80 GPH | Flush pump failure; valve stuck; charcoal filter clogged | Sensor issue |
| End-of-flush TDS | — | 1000 PPM | — | Flush not cleaning membranes; insufficient volume; charcoal filter saturated; flush too short |
| Battery voltage | 22.0 V | — | Battery depleted during run+flush | — |

### Model-Specific Values

Thresholds are auto-detected from the device model. The following table shows key differences:

| Parameter | Newport 1000 | Newport 700 | Newport 400 | Ventura 150/200 | Catalina |
|-----------|-------------|-------------|-------------|-----------------|----------|
| Pressure limit | 250 PSI | 200 PSI | 150 PSI | 125 PSI | 130 PSI |
| Rated production | 41 GPH | 29 GPH | 17 GPH | 6-8 GPH | 14 GPH |
| Flow min (anomaly) | 20 GPH | 14 GPH | 8 GPH | 3 GPH | 7 GPH |
| Flow max (anomaly) | 53 GPH | 38 GPH | 22 GPH | 10 GPH | 18 GPH |

### Common Values (All Models)

| Parameter | Value | Source |
|-----------|-------|--------|
| PPM rejection threshold | 748 PPM | Spectra factory default |
| Membrane replacement | 700-800 PPM | Spectra recommendation |
| End-of-flush TDS | < 1000 PPM | Spectra spec |
| Operating temperature | 36-110°F | Spectra spec |
| Temp effect on output | -50% at 48°F, +25% at 90°F | Relative to 77°F baseline |
| Battery voltage minimum | 22.0 V | — |
| Motor voltage minimum | ≥90% of source | Spectra spec |
| Salt rejection | 99.2% | Membrane spec |
| Flush duration default | 5 minutes | Spectra factory default |
| Boost sensor target | 15 PSIA | Alarm below 10 |

### Anomaly Response Guide

| Anomaly | Phase | What To Do |
|---------|-------|------------|
| **Feed pressure low** | Running | Check/replace prefilter. Inspect seawater intake for blockage or air leak. Verify boost pump voltage (≥90% of source). |
| **Feed pressure high** | Running | Chemical-clean membranes. Inspect brine discharge line for blockage or kink. |
| **Boost pressure low** | Running | Check boost pump operation and wiring. Verify voltage supply. Replace prefilter if restricting flow. |
| **Product flow low** | Running | Check membrane condition. Verify operating pressure. Note water temperature (cold = lower output). Consider membrane age. |
| **Product flow high** | Running | Inspect product tube O-rings for bypass (salt water contaminating product). Check brine seal alignment. |
| **Product TDS high** | Running | Check membrane age — gradual rise to 700-800 PPM means replacement time. Inspect O-rings on product tube end plugs. Check brine seal orientation. |
| **Battery voltage low** | Any | Ensure adequate charging during watermaker operation. Reduce other loads. Check battery bank health. |
| **Water temp low** | Running | Normal — cold water reduces output. Allow longer run times. Output drops ~50% at 48°F per Spectra specs. |
| **Feed pressure low** | Flushing | Check flush pump operation. Verify flush valve opens. Check freshwater supply pressure. |
| **Feed pressure high** | Flushing | High-pressure pump may not have disengaged. Inspect valves. |
| **Product flow low** | Flushing | Check flush pump. Inspect charcoal filter for clogging. Verify flush valve operation. |
| **End-of-flush TDS high** | Flushing | Charcoal filter may be saturated — replace. Flush duration may be too short. Check flush water volume. |

## Entities

### Sensors

| Entity | Description |
|--------|-------------|
| `sensor.spectra_state` | Current state: off, booting, prompt, idle, starting, running, flushing, error |
| `sensor.spectra_product_flow` | Fresh water production rate (L/h) |
| `sensor.spectra_boost_pressure` | Boost pump pressure (psi) |
| `sensor.spectra_feed_pressure` | Membrane feed pressure (psi) |
| `sensor.spectra_product_tds` | Product water TDS/salinity (ppm) |
| `sensor.spectra_water_temperature` | Water temperature (°C) |
| `sensor.spectra_water_quality` | Quality level: excellent, good, acceptable, poor, undrinkable |
| `sensor.spectra_water_destination` | Tank or overboard |
| `sensor.spectra_filter_condition` | Prefilter condition (%) |
| `sensor.spectra_elapsed_time` | Current run elapsed time |
| `sensor.spectra_remaining_time` | Remaining time (timed runs) |
| `sensor.spectra_current_run_liters` | Live liters produced in current run |
| `sensor.spectra_total_liters` | Total liters produced (Energy Dashboard compatible, only counts tank fill) |
| `sensor.spectra_total_hours` | Total production hours |
| `sensor.spectra_last_run_duration` | Last run duration |
| `sensor.spectra_last_run_avg_ppm` | Last run average TDS |
| `sensor.spectra_last_flush` | When the last flush completed |
| `sensor.spectra_days_since_flush` | Days since last flush (for auto-flush automations) |
| `sensor.spectra_prefilter_last_changed` | Date prefilters were last replaced |
| `sensor.spectra_prefilter_days_ago` | Days since last prefilter change |
| `sensor.spectra_prefilter_hours_since_change` | Production hours since last prefilter change |

### Binary Sensors

| Entity | Description |
|--------|-------------|
| `binary_sensor.spectra_connected` | WebSocket connection alive |
| `binary_sensor.spectra_running` | Watermaker is producing or flushing |
| `binary_sensor.spectra_filling_tank` | Water is going to tank (not diverting overboard) |

### Controls

| Entity | Type | Description |
|--------|------|-------------|
| `switch.spectra_power` | switch | Controls the outlet (only if configured). Blocks power-off during flush. |
| `button.spectra_start` | button | Start making water. Powers on if needed, dismisses prompts, sets duration, starts autorun. |
| `button.spectra_stop` | button | Stop the watermaker (triggers flush) |
| `button.spectra_flush` | button | Manual freshwater flush from idle |
| `button.spectra_reset_prefilter` | button | Reset prefilter date and hours counter |
| `select.spectra_water_destination` | select | Toggle tank vs. overboard while running |
| `number.spectra_run_duration` | number | Duration for next start (0.5–8.0 hours, default 2.0) |
| `number.spectra_tank_full_threshold` | number | Auto-stop threshold (50–100%, default 98%) |

## How It Works

The Spectra Connect module exposes two WebSocket endpoints on the local network:

- **Port 9000** — UI stream (mirrors the touchscreen display). Used for state detection and sending control commands.
- **Port 9001** — Data stream. Provides raw sensor readings ~1/second as JSON.

The integration maintains persistent connections to both, with automatic reconnection. No cloud services, no internet required. All communication is local.

### Power Management

If you configure a power outlet switch, the integration handles the full lifecycle:

1. **Power on** the outlet
2. **Wait** for the Spectra to boot and WebSocket to become available
3. **Auto-dismiss** boot prompts (power loss warning, chemical storage question)
4. **Start** the watermaker
5. After stop, **wait for flush** to complete (3–10 min, protects membranes)
6. **Power off** the outlet once idle (configurable delay, default 5 min)

### Water Quality Tracking

During each run, the integration ignores TDS readings from the first 60 seconds and while water is being diverted overboard (startup phase). Once the watermaker switches to filling the tank, it begins tracking min/max/avg TDS. This gives clean quality data for long-term trend analysis.

### Water Quality (TDS)

| Level | TDS (ppm) | Meaning |
|-------|-----------|---------|
| Excellent | < 200 | Fresh membranes, optimal conditions |
| Good | 200–350 | Normal for Spectra Newport systems |
| Acceptable | 350–500 | Within WHO/EPA guidelines |
| Poor | 500–700 | Membrane cleaning recommended |
| Undrinkable | > 700 | Do not fill tanks |

## Run History

The integration stores the last 50 runs in `.storage/spectra_watermaker_history`. Each entry includes:

- Start/end timestamps and duration
- Liters produced (only while filling tank)
- Min/max/avg TDS during fill
- Average feed pressure and water temperature
- Time from start to tank fill
- Stop reason (manual, timer, tank_full, error)

Access via the `spectra_watermaker.get_run_history` service call for dashboards or automations.

## Compatibility

| Device | Status |
|--------|--------|
| Spectra Newport 1000 | Tested |
| Spectra Newport 400c | Expected to work |
| Spectra Catalina series | Expected to work |
| Spectra Ventura series | Expected to work |
| Other Spectra Connect models | Should work — please report |

Requires the **Spectra Connect module** (the module that provides the web interface at the watermaker's IP address).

## Troubleshooting

Enable debug logging:

```yaml
logger:
  default: info
  logs:
    custom_components.spectra_watermaker: debug
```

### Common Issues

- **Cannot connect during setup** — Ensure the watermaker is powered on and the Spectra Connect module is on your network. Try accessing `http://<IP>` in a browser.
- **State stuck on "booting"** — The watermaker may be showing a prompt that needs dismissal. Check the Spectra web interface.
- **Tank auto-stop not firing** — Verify your tank sensors are reporting values in percent (0–100). Check the threshold setting.
- **Salinity error on cold start** — Normal for the first 1-2 minutes. The integration retries once automatically. If it persists, check membrane condition.

## Contributing

Issues and pull requests welcome at [GitHub](https://github.com/tomerddd/ha-spectra-watermaker).

## License

MIT
