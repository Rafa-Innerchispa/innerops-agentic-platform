import unittest
from unittest.mock import patch
from pymongo.errors import ConnectionFailure, DuplicateKeyError
import importlib.util
from pathlib import Path

# Load the candidate itself; the legacy alias may point to the live runtime.
_MODULE_PATH = Path(__file__).resolve().parents[1] / "inneros_core_runtime" / "whatsapp_dual_node_monitor.py"
_SPEC = importlib.util.spec_from_file_location("candidate_whatsapp_dual_node_monitor", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
monitor = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(monitor)


class Collection:
    def __init__(self): self.docs = {}
    def find_one(self, query): return self.docs.get(query.get("_id"))
    def update_one(self, query, update, upsert=False):
        key = query.get("_id")
        doc = self.docs.setdefault(key, {"_id": key})
        doc.update(update.get("$set", {}))
    def insert_one(self, doc):
        key = doc.get("_id", f"audit-{len(self.docs)}")
        if key in self.docs:
            raise DuplicateKeyError("duplicate _id")
        self.docs[key] = dict(doc)
    def find_one_and_update(self, query, update, upsert=False, return_document=None):
        key = query["_id"]
        old = self.docs.get(key)
        if old is not None:
            clauses = query.get("$or", [])
            allowed = any(
                ("holder" in clause and old.get("holder") == clause["holder"])
                or (
                    "expires_at" in clause
                    and "$lte" in clause["expires_at"]
                    and str(old.get("expires_at") or "") <= clause["expires_at"]["$lte"]
                )
                or (
                    "expires_at" in clause
                    and clause["expires_at"].get("$exists") is False
                    and "expires_at" not in old
                )
                for clause in clauses
            )
            if not allowed:
                if upsert:
                    raise DuplicateKeyError("lease _id owned by another node")
                return None
            old.update(update.get("$set", {}))
            return dict(old)
        if not upsert: return None
        doc = {"_id": key, **update.get("$set", {})}
        self.docs[key] = doc
        return dict(doc)


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

    def test_lease_cannot_be_stolen_until_expiry(self):
        with patch.object(monitor.mongo_store, "get_db", return_value=self.db):
            self.assertTrue(monitor.acquire_lease("intel"))
            self.assertFalse(monitor.acquire_lease("amd"))
            self.assertTrue(monitor.acquire_lease("intel"))
            doc = self.db[monitor.LEASE_COLLECTION].docs["dual-node-leader"]
            doc["expires_at"] = "2020-01-01T00:00:00+00:00"
            self.assertTrue(monitor.acquire_lease("amd"))
            self.assertFalse(monitor.acquire_lease("intel"))

    def test_lease_db_failure_never_promotes_both_nodes(self):
        with patch.object(monitor.mongo_store, "get_db", side_effect=ConnectionFailure("offline")):
            self.assertFalse(monitor.acquire_lease("intel"))
            self.assertFalse(monitor.acquire_lease("amd"))

    def test_lease_election_is_one_atomic_operation(self):
        coll = self.db[monitor.LEASE_COLLECTION]
        with patch.object(monitor.mongo_store, "get_db", return_value=self.db), patch.object(
            coll, "find_one", side_effect=AssertionError("read-before-write forbidden")
        ):
            self.assertTrue(monitor.acquire_lease("intel"))
            self.assertFalse(monitor.acquire_lease("amd"))

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
