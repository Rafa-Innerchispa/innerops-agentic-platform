from pathlib import Path
import sys
import unittest
from unittest.mock import patch

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from raphiia_openai import productivity_metrics, self_heal_metrics


class _Collection:
    def __init__(self):
        self.rows = []

    def find_one(self, query, projection=None):
        for row in reversed(self.rows):
            if all(row.get(k) == v for k, v in query.items()):
                return dict(row)
        return None

    def update_one(self, query, update, upsert=False):
        existing = self.find_one(query)
        row = dict(existing or {})
        if not existing:
            row.update(update.get("$setOnInsert") or {})
        row.update(update.get("$set") or {})
        self.rows = [r for r in self.rows if not all(r.get(k) == v for k, v in query.items())]
        self.rows.append(row)


class _DB:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        self.collections.setdefault(name, _Collection())
        return self.collections[name]


class ProductivitySelfHealMetricsTests(unittest.TestCase):
    def test_measured_event_calculates_verified_human_hours_returned(self):
        event = productivity_metrics.calculate_event(
            {
                "task_key": "demo",
                "human_baseline_minutes": 120,
                "assisted_minutes": 10,
                "measurement_class": "measured",
                "verified": True,
            }
        )
        self.assertEqual(event["saved_minutes"], 110)
        self.assertEqual(event["human_hours_returned"], 1.8333)
        self.assertEqual(event["reduction_percent"], 91.67)
        self.assertEqual(event["speedup"], 12.0)
        self.assertTrue(event["verified"])

    def test_self_heal_without_baseline_never_counts_roi(self):
        db = _DB()
        with patch.object(self_heal_metrics.mongo_store, "get_db", return_value=db), patch.object(
            self_heal_metrics.productivity_metrics, "save_productivity_event"
        ) as save_productivity:
            result = self_heal_metrics.record_self_heal_incident(
                {
                    "incident_id": "heal_no_baseline",
                    "service_id": "mcp",
                    "repair_duration_seconds": 9,
                    "repair_action_ok": True,
                    "verified_recovered": True,
                    "automatic": True,
                    "human_intervention_minutes": 0,
                }
            )
        self.assertTrue(result["ok"])
        self.assertFalse(result["roi_counted"])
        self.assertEqual(result["incident"]["human_hours_returned"], 0.0)
        self.assertIsNone(result["incident"]["manual_baseline_minutes"])
        save_productivity.assert_not_called()

    def test_verified_measured_baseline_links_self_heal_to_productivity(self):
        db = _DB()
        db[self_heal_metrics.BASELINE_COLLECTION].update_one(
            {"service_id": "portal"},
            {
                "$set": {
                    "service_id": "portal",
                    "manual_baseline_minutes": 15.0,
                    "measurement_class": "measured",
                    "verified": True,
                    "evidence_refs": ["runbook:portal-recovery"],
                }
            },
            upsert=True,
        )
        with patch.object(self_heal_metrics.mongo_store, "get_db", return_value=db), patch.object(
            self_heal_metrics.productivity_metrics,
            "save_productivity_event",
            return_value={"ok": True},
        ) as save_productivity:
            result = self_heal_metrics.record_self_heal_incident(
                {
                    "incident_id": "heal_with_baseline",
                    "service_id": "portal",
                    "repair_duration_seconds": 45,
                    "repair_action_ok": True,
                    "verified_recovered": True,
                    "automatic": True,
                    "human_intervention_minutes": 0,
                }
            )
        self.assertTrue(result["roi_counted"])
        self.assertEqual(result["incident"]["saved_minutes"], 15.0)
        self.assertEqual(result["incident"]["human_hours_returned"], 0.25)
        payload = save_productivity.call_args.args[0]
        self.assertEqual(payload["human_baseline_minutes"], 15.0)
        self.assertEqual(payload["assisted_minutes"], 0)
        self.assertEqual(payload["measurement_class"], "measured")
        self.assertTrue(payload["verified"])


if __name__ == "__main__":
    unittest.main()
