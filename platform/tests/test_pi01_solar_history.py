from pathlib import Path
import sys
import unittest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from scripts.record_pi01_xmart_solar_history import as_float, bool01
from scripts.summarize_pi01_xmart_solar_history import estimate_energy


class Pi01SolarHistoryTests(unittest.TestCase):
    def test_state_normalizers(self):
        self.assertEqual(as_float("12.5"), 12.5)
        self.assertIsNone(as_float("unavailable"))
        self.assertEqual(bool01("on"), 1)
        self.assertEqual(bool01("off"), 0)
        self.assertIsNone(bool01("unknown"))

    def test_energy_estimate_skips_large_gaps(self):
        rows = [
            {"ts_utc": "2026-09-13T00:00:00+00:00", "output_active_w": 600, "pv_charging_power_w": 300, "breaker_power_kw": 0.7},
            {"ts_utc": "2026-09-13T00:01:00+00:00", "output_active_w": 600, "pv_charging_power_w": 300, "breaker_power_kw": 0.7},
            {"ts_utc": "2026-09-13T01:00:00+00:00", "output_active_w": 600, "pv_charging_power_w": 300, "breaker_power_kw": 0.7},
        ]

        out = estimate_energy(rows)

        self.assertEqual(out["estimated_output_kwh"], 0.01)
        self.assertEqual(out["estimated_pv_charge_kwh"], 0.005)
        self.assertEqual(out["estimated_breaker_kwh_from_power"], 0.012)


if __name__ == "__main__":
    unittest.main()
