import unittest
from unittest.mock import patch

from raphiia_openai import whatsapp_dual_node_monitor as monitor


class Collection:
    def __init__(self): self.docs = {}
    def find_one(self, query): return self.docs.get(query.get("_id"))
    def update_one(self, query, update, upsert=False):
        key = query.get("_id")
        doc = self.docs.setdefault(key, {"_id": key})
        doc.update(update.get("$set", {}))
    def insert_one(self, doc): self.docs[f"audit-{len(self.docs)}"] = dict(doc)


class DB:
    def __init__(self): self.cols = {}
    def __getitem__(self, name): return self.cols.setdefault(name, Collection())


class TestDualNodeMonitor(unittest.TestCase):
    def setUp(self): self.db = DB()

    def test_two_failures_alert_once_and_recovery_alerts_once(self):
        down = lambda: {"node:amd": {"healthy": False, "node": "amd", "label": "Servidor .5", "state": "unreachable"}}
        up = lambda: {"node:amd": {"healthy": True, "node": "amd", "label": "Servidor .5", "state": "reachable"}}
        sent = []
        with patch.object(monitor.mongo_store, "get_db", return_value=self.db), patch.object(
            monitor.mongo_store, "log_coordination"
        ), patch.object(monitor, "_destinations", return_value=["593fixture"]), patch.object(
            monitor, "_send_failover", side_effect=lambda text, destination, node: sent.append((text, destination, node)) or True
        ):
            first = monitor.run_monitor_cycle(require_leader=False, probe=down)
            second = monitor.run_monitor_cycle(require_leader=False, probe=down)
            third = monitor.run_monitor_cycle(require_leader=False, probe=down)
            recovered = monitor.run_monitor_cycle(require_leader=False, probe=up)
        self.assertEqual(first["transitions"], [])
        self.assertEqual(second["transitions"][0]["kind"], "down")
        self.assertEqual(third["transitions"], [])
        self.assertEqual(recovered["transitions"][0]["kind"], "recovered")
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0][2], "amd")

    def test_active_lease_keeps_second_monitor_in_standby(self):
        with patch.object(monitor.mongo_store, "get_db", return_value=self.db):
            self.assertTrue(monitor.acquire_lease("node-a"))
            self.assertFalse(monitor.acquire_lease("node-b"))

    def test_unreachable_node_emits_one_node_probe_not_service_storm(self):
        snapshot = {
            "items": [
                {"ok": True, "healthy": False, "node": "primary", "node_label": ".4", "service_id": "mcp", "label": "MCP", "system_state": "unknown", "health": "down"},
                {"ok": True, "healthy": True, "node": "amd", "node_label": ".5", "service_id": "mcp", "label": "MCP", "system_state": "active", "health": "up"},
            ]
        }
        with patch.object(monitor.whatsapp_service_ops, "status_snapshot", return_value=snapshot), patch.object(
            monitor.whatsapp_service_ops, "node_reachable", side_effect=lambda node: node == "amd"
        ):
            probes = monitor._probe_snapshot()
        self.assertIn("node:primary", probes)
        self.assertNotIn("service:primary:mcp", probes)
        self.assertIn("service:amd:mcp", probes)


if __name__ == "__main__": unittest.main()
