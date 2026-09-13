from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from scripts.monitor_pi01_xmart_solar_alerts import build_events
from scripts.publish_pi01_xmart_solar_to_ha import infer_mode


class Pi01SolarMonitorTests(unittest.TestCase):
    def test_infer_backup_float_when_grid_present_and_battery_full(self):
        telemetry = {
            "grid_voltage_v": 123.2,
            "ac_output_voltage_v": 123.2,
            "battery_capacity_percent": 100,
            "battery_voltage_v": 28.8,
            "battery_charging_current_a": 1,
            "battery_discharge_current_a": 0,
            "pv_charging_power_w": 0,
        }

        inferred = infer_mode(telemetry)

        self.assertEqual(inferred["mode"], "utility_present_backup_float")
        self.assertTrue(inferred["grid_present"])
        self.assertFalse(inferred["battery_mode"])

    def test_grid_lost_generates_battery_backup_event(self):
        telemetry = {
            "grid_voltage_v": 0.0,
            "ac_output_voltage_v": 120.0,
            "ac_output_active_power_w": 500,
            "output_load_percent": 21,
            "battery_voltage_v": 25.5,
            "battery_capacity_percent": 80,
            "battery_charging_current_a": 0,
            "battery_discharge_current_a": 18,
            "pv_charging_power_w": 0,
            "inverter_heat_sink_temperature_c": 42,
        }
        state = {"last_conditions": {"grid_present": True}}

        events = build_events({"ok": True, "telemetry": telemetry}, state, datetime.now(timezone.utc))

        self.assertIn("grid_lost", [event["event"] for event in events])

    def test_grid_restored_generates_restore_event(self):
        telemetry = {
            "grid_voltage_v": 122.0,
            "ac_output_voltage_v": 122.0,
            "ac_output_active_power_w": 450,
            "output_load_percent": 19,
            "battery_voltage_v": 27.5,
            "battery_capacity_percent": 92,
            "battery_charging_current_a": 3,
            "battery_discharge_current_a": 0,
            "pv_charging_power_w": 0,
            "inverter_heat_sink_temperature_c": 40,
        }
        state = {"last_conditions": {"grid_present": False}}

        events = build_events({"ok": True, "telemetry": telemetry}, state, datetime.now(timezone.utc))

        self.assertIn("grid_restored", [event["event"] for event in events])

    def test_critical_battery_generates_critical_event(self):
        telemetry = {
            "grid_voltage_v": 0.0,
            "ac_output_voltage_v": 120.0,
            "ac_output_active_power_w": 500,
            "output_load_percent": 21,
            "battery_voltage_v": 22.3,
            "battery_capacity_percent": 14,
            "battery_charging_current_a": 0,
            "battery_discharge_current_a": 20,
            "pv_charging_power_w": 0,
            "inverter_heat_sink_temperature_c": 42,
        }

        events = build_events({"ok": True, "telemetry": telemetry}, {}, datetime.now(timezone.utc))

        self.assertIn("battery_critical", [event["event"] for event in events])

    def test_reader_error_is_suppressed_until_streak_threshold(self):
        state = {"reader_error_streak": 1}

        events = build_events(
            {"ok": False, "error": "ssh_reader_failed", "ssh_target": "rlopez@192.168.1.97"},
            state,
            datetime.now(timezone.utc),
        )

        self.assertEqual(events, [])

    def test_reader_error_message_includes_diagnostics_after_threshold(self):
        state = {"reader_error_streak": 2}

        events = build_events(
            {
                "ok": False,
                "error": "ssh_auth_failed",
                "returncode": 255,
                "ssh_target": "rlopez@192.168.1.97",
                "remote_reader": "/opt/inneros/solar_xmart_mpp_read.py",
                "stderr": "Permission denied (publickey,password).",
            },
            state,
            datetime.now(timezone.utc),
        )

        self.assertEqual(events[0]["event"], "reader_error")
        self.assertIn("ssh_auth_failed", events[0]["message"])
        self.assertIn("streak=3", events[0]["message"])
        self.assertIn("192.168.1.97", events[0]["message"])


if __name__ == "__main__":
    unittest.main()
