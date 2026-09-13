from pathlib import Path
import sys
import unittest
from unittest.mock import patch

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from inneros_core_runtime import homeassistant_client
from raphiia_openai import home_ops_daemon
from inneros_core_runtime.agents import pool_agent_runners


class AG32HomeOpsCycleTests(unittest.TestCase):
    def test_client_exports_run_home_ops_cycle_wrapper(self):
        with patch.object(home_ops_daemon, "run_cycle", return_value={"ok": True, "steps": [{"ha_snapshot": {"ok": True}}]}):
            result = homeassistant_client.run_home_ops_cycle(trigger="unit-test")

        self.assertTrue(result["ok"])
        self.assertEqual(result["trigger"], "unit-test")
        self.assertEqual(result["entrypoint"], "homeassistant_client.run_home_ops_cycle")
        self.assertEqual(result["steps"][0]["ha_snapshot"], {"ok": True})

    def test_ag32_runner_uses_home_ops_cycle_without_attribute_error(self):
        with patch.object(home_ops_daemon, "run_cycle", return_value={"ok": True, "steps": []}):
            result = pool_agent_runners._home_ops("runner-test")

        self.assertTrue(result["ok"])
        self.assertEqual(result["trigger"], "runner-test")
        self.assertEqual(result["entrypoint"], "homeassistant_client.run_home_ops_cycle")


if __name__ == "__main__":
    unittest.main()
