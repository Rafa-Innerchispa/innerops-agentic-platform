import unittest
from unittest.mock import patch

from inneros_core_runtime import productivity_metrics as pm
from inneros_core_runtime.tests.test_external_repair_agent import FakeDb


class ProductivityMetricsTests(unittest.TestCase):
    def test_calculate_event(self):
        event = pm.calculate_event({"task_key": "demo", "human_baseline_minutes": 120, "assisted_minutes": 10})

        self.assertEqual(event["saved_minutes"], 110)
        self.assertEqual(event["reduction_percent"], 91.67)
        self.assertEqual(event["speedup"], 12)

    def test_save_event_is_idempotent_by_task_key(self):
        db = FakeDb()
        with patch.object(pm.mongo_store, "get_db", return_value=db):
            first = pm.save_productivity_event({"task_key": "demo", "human_baseline_minutes": 120, "assisted_minutes": 10})
            second = pm.save_productivity_event({"task_key": "demo", "human_baseline_minutes": 90, "assisted_minutes": 30})
            summary = pm.summarize_productivity_events()

        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(db[pm.COLLECTION].count_documents({}), 1)
        self.assertEqual(summary["saved_minutes"], 60)


if __name__ == "__main__":
    unittest.main()
