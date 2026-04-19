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

### Control
- **Start / Stop** — fill tank, autofill (liters or hours), and stop via HA services or dashboard buttons
- **Water destination toggle** — switch between tank fill and overboard
- **Power management** — optional smart outlet integration to power on/off the watermaker, with automatic boot prompt dismissal
- **Tank full auto-stop** — connect your tank level sensors (any source) and set a threshold; the integration stops the watermaker when tanks are full (30s debounce to handle sloshing)

### History & Maintenance
- **Run history** — logs each production run with duration, liters produced, min/max/avg TDS, stop reason, and time-to-fill
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
6. **Power off** the outlet once idle

### Water Quality Tracking

During each run, the integration ignores TDS readings from the first 60 seconds and while water is being diverted overboard (startup phase). Once the watermaker switches to filling the tank, it begins tracking min/max/avg TDS. This gives clean quality data for long-term trend analysis.

The **time-to-fill** metric (seconds from start until water quality is good enough to fill) trends upward as membranes age or prefilters need replacing.

### Water Quality (TDS)

TDS (Total Dissolved Solids) measures how well the RO membrane rejects salt. The integration provides a real-time quality level based on product water TDS:

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

## Contributing

Issues and pull requests welcome at [GitHub](https://github.com/tomerddd/ha-spectra-watermaker).

## License

MIT
