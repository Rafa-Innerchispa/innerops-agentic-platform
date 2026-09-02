import importlib
import unittest


class OpsTaskAlertsCompatTests(unittest.TestCase):
    def test_legacy_notifications_import_exposes_ops_alerts(self):
        module = importlib.import_module("raphiia_openai.notifications.ops_task_alerts")
        self.assertTrue(callable(module.notify_ops_transition))
        self.assertTrue(callable(module.notify_dev_swarm_outcome))
        self.assertIn("ops_task_alerts.py", str(module.__file__))


if __name__ == "__main__":
    unittest.main()
