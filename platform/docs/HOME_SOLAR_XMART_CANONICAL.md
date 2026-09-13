# Home Solar Xmart Canonical Inventory

Date: 2026-09-13

This file is the canonical technical note for the current home solar monitoring integration. It documents what is connected, what InnerOS can read safely, and which automation is enabled.

## Hardware

- Inverter: XMART XSI-B-120-3K-24-MPP / XSI-B-120V-3K family.
- Inverter class: 120 Vac single phase, 3 kVA / 2400 W, 24 VDC battery bank, MPPT.
- PV input limits: up to 2000 W, maximum PV open-circuit voltage 145 VDC, MPPT working range 30-115 VDC.
- Solar panels: 4 x XMART XPV-545-42M, 545 Wp each, 2180 Wp total.
- Panel wiring: 2S2P.
- Expected array values: Vmp about 83.5 V, Voc about 99.2 V, Imp about 26.1 A, Isc about 27.9 A.
- Battery: TECLAM LiFePO4 25.6 V 230 Ah, about 5888 Wh, with BMS.
- Battery range: 21.6-29.6 V. Max charge 29.2 V. Float target 28.8 V. Low cutoff initial policy 22.4 V.
- Important safety rule: do not mix the old degraded GEL bank with the LiFePO4 bank.

## Current Operating Policy

The inverter is currently used as backup/utility-first:

- With grid present, the house load is served while the battery remains full/float.
- If utility power fails, the inverter should continue output from the battery.
- Solar production is observed through the inverter telemetry, but InnerOS does not yet write inverter settings automatically.

Recommended initial Xmart settings documented by ChatGPT and owner context:

- P05: USE/custom battery.
- P26: 28.8 V.
- P27: 28.8 V.
- P29: 22.4 V initial low cutoff.
- P02: 60 A total charge current.
- P11: 30 A utility charge current.
- P01: UTI for backup mode now; SOL/SBU may be evaluated after daylight trend evidence.
- P12: AC fallback threshold 22.0-25.5 V according to tested behavior.
- P13: return-to-battery FULL or 24-29 V according to tested behavior.
- P16/P31: charging/output priorities require safe manual review before any write action.

## Runtime Integration

Physical path:

- Inverter USB HID device: 0665:5161.
- Reader node: InnerOs-Pi01 at 192.168.1.97.
- Runtime reader: `/opt/inneros/solar_xmart_mpp_read.py`.
- Protocol: PI30 using read-only QPI and QPIGS queries.
- Publisher node: Intel `.4`.
- Home Assistant publisher: `/home/rlopez/inneros/inneros_core/platform/scripts/publish_pi01_xmart_solar_to_ha.py`.
- WhatsApp alert monitor: `/home/rlopez/inneros/inneros_core/platform/scripts/monitor_pi01_xmart_solar_alerts.py`.

Home Assistant entities:

- `sensor.inneros_pi01_solar_status`
- `sensor.inneros_pi01_solar_output_power`
- `sensor.inneros_pi01_solar_battery_voltage`
- `sensor.inneros_pi01_solar_battery_capacity`
- `sensor.inneros_pi01_solar_load`
- `sensor.inneros_pi01_solar_pv_voltage`
- `sensor.inneros_pi01_solar_temperature`
- `sensor.inneros_pi01_solar_grid_voltage`
- `sensor.inneros_pi01_solar_output_voltage`
- `sensor.inneros_pi01_solar_mode`
- `binary_sensor.inneros_pi01_solar_grid_present`
- `binary_sensor.inneros_pi01_solar_battery_mode`

Systemd user timers on Intel `.4`:

- `inneros-pi01-solar-ha.timer`: publishes telemetry to Home Assistant every 60 seconds.
- `inneros-pi01-solar-alerts.timer`: checks alert conditions every 60 seconds and sends WhatsApp only on transitions or critical cooldown.

## What InnerOS Can Read

Current safe telemetry includes:

- Grid voltage/frequency.
- AC output voltage/frequency.
- Output apparent and active power.
- Output load percent.
- Battery voltage.
- Battery reported capacity.
- Battery charge/discharge current.
- Inverter heatsink temperature.
- PV input voltage/current and PV charging power.
- Raw QPIGS fields for forensic replay.

InnerOS can see aggregate PV production from the inverter. It cannot see individual panel health, string imbalance, connector problems, or battery cell-level BMS details unless a separate BMS/PV data interface is added.

## Alert Rules

WhatsApp alerts are enabled for:

- Grid lost / battery backup mode.
- Grid restored.
- Low battery.
- Critical battery.
- High inverter temperature.
- Reader failure.

The monitor stores state in `/home/rlopez/data/ralfia/solar_xmart_alert_state.json` to avoid repeated spam. Normal polling should stay quiet when nothing important changes.

## Latest Verified Live Reading

At 2026-09-13 around 05:20 UTC, the inverter returned:

- Grid present: 123.7 V / 60.0 Hz.
- Output present: 123.7 V / 60.0 Hz.
- Output load: 595 W, 24%.
- Battery: 28.8 V, 100%, charging current 1 A, discharge current 0 A.
- PV: 0 W and 0 V at the time of reading.
- Temperature: 39 C.

Interpretation: utility power is present, the inverter is operating normally as backup/float, the battery is full, and PV is zero because this was a night reading. Daylight trend evidence is still needed before changing solar priority behavior.

## Next Safe Steps

1. Collect daylight telemetry for at least one clear morning/noon window.
2. Confirm whether PV voltage rises into the expected MPPT range during sun.
3. Compare house daytime load with PV charging power and battery state.
4. Only after evidence, decide whether to test SOL/SBU priority.
5. Keep all inverter writes manual/owner-approved until a write guard exists.
