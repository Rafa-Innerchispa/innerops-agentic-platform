from pathlib import Path
import sys
import unittest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from inneros_core_runtime import energy_history


class EnergyHistoryTests(unittest.TestCase):
    def test_parse_naive_guayaquil_to_utc(self):
        out = energy_history._parse_dt("2026-09-17T18:59:00", "America/Guayaquil")
        self.assertEqual(out.isoformat(), "2026-09-17T23:59:00+00:00")

    def test_invalid_range(self):
        out = energy_history.solar_history_query(
            "2026-09-18T01:00:00+00:00",
            "2026-09-18T00:00:00+00:00",
            include_ha=False,
        )
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "end_before_start")

    def test_numeric_stats(self):
        rows = [
            {"ts_utc": "2026-09-17T23:50:00+00:00", "output_active_w": 500},
            {"ts_utc": "2026-09-17T23:51:00+00:00", "output_active_w": 900},
        ]
        out = energy_history._numeric_stats(rows, "output_active_w")
        self.assertEqual(out["max"], 900.0)
        self.assertEqual(out["avg"], 700.0)


if __name__ == "__main__":
    unittest.main()
