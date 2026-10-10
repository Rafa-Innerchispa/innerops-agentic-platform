"""Dual-node monitor regression and single-leader safety, testing the candidate file."""
from __future__ import annotations

import importlib.util
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock
from types import SimpleNamespace
from unittest.mock import patch

from pymongo.errors import DuplicateKeyError

SOURCE = Path(__file__).resolve().parents[1] / "inneros_core_runtime" / "whatsapp_dual_node_monitor.py"
SPEC = importlib.util.spec_from_file_location("candidate_ha_monitor", SOURCE)
assert SPEC and SPEC.loader
monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitor)


class Collection:
    def __init__(self):
        self.docs = {}
        self.lock = Lock()

    def find_one(self, query):
        with self.lock:
            return self.docs.get(query.get("_id"))

    def update_one(self, query, update, upsert=False):
        key = query.get("_id")
        with self.lock:
            existed = key in self.docs
            doc = self.docs.get(key)
            if "$or" in query:
                if doc is None:
                    return SimpleNamespace(matched_count=0)
                approved = any(
                    ("holder" in cond and doc.get("holder") == cond["holder"])
                    or ("expires_at" in cond and "$lte" in cond["expires_at"]
                        and str(doc.get("expires_at") or "") <= cond["expires_at"]["$lte"])
                    or ("expires_at" in cond and cond["expires_at"].get("$exists") is False
                        and "expires_at" not in doc)
                    for cond in query["$or"]
                )
                if not approved:
                    return SimpleNamespace(matched_count=0)
            if doc is None and not upsert:
                return SimpleNamespace(matched_count=0)
            doc = self.docs.setdefault(key, {"_id": key})
            doc.update(update.get("$set", {}))
            return SimpleNamespace(matched_count=1 if existed else 0)

    def insert_one(self, doc):
        with self.lock:
            key = doc.get("_id") or f"audit-{len(self.docs)}"
            if key in self.docs:
                raise DuplicateKeyError("duplicate _id")
            self.docs[key] = dict(doc)
            return SimpleNamespace(inserted_id=key)


class DB:
    def __init__(self):
        self.cols = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, Collection())


class TestDualNodeMonitor(unittest.TestCase):
    def setUp(self):
        self.db = DB()

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

    def test_expired_lease_can_transfer_to_other_node(self):
        with patch.object(monitor.mongo_store, "get_db", return_value=self.db):
            self.assertTrue(monitor.acquire_lease("amd"))
            self.assertTrue(monitor.acquire_lease("amd"))
            self.assertFalse(monitor.acquire_lease("intel"))
            self.db[monitor.LEASE_COLLECTION].docs["dual-node-leader"]["expires_at"] = "2020-01-01T00:00:00+00:00"
            self.assertTrue(monitor.acquire_lease("intel"))
            self.assertEqual(self.db[monitor.LEASE_COLLECTION].docs["dual-node-leader"]["holder"], "intel")

    def test_concurrent_nodes_cannot_both_claim_leader(self):
        barrier = Barrier(2)
        def claim(holder):
            barrier.wait(timeout=5)
            return monitor.acquire_lease(holder)
        with patch.object(monitor.mongo_store, "get_db", return_value=self.db):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(claim, ("amd", "intel")))
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 1)

    def test_unreachable_node_suppresses_per_service_alert_storm(self):
        sample = {"items": [
            {"ok": True, "healthy": False, "node": "primary", "node_label": ".4",
             "service_id": "mcp", "label": "MCP", "system_state": "unknown", "health": "down"},
            {"ok": True, "healthy": True, "node": "amd", "node_label": ".5",
             "service_id": "mcp", "label": "MCP", "system_state": "active", "health": "up"},
        ]}
        with patch.object(monitor.whatsapp_service_ops, "status_snapshot", return_value=sample), patch.object(
            monitor.whatsapp_service_ops, "node_reachable", side_effect=lambda n: n == "amd"
        ):
            probes = monitor._probe_snapshot()
        self.assertIn("node:primary", probes)
        self.assertNotIn("service:primary:mcp", probes)
        self.assertIn("service:amd:mcp", probes)


if __name__ == "__main__":
    unittest.main()
