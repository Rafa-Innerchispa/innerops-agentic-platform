"""Tests for canonical IDE Task Bridge."""
from __future__ import annotations

import unittest

from inneros_core_runtime import ide_task_bridge


class IdeTaskBridgeTests(unittest.TestCase):
    def test_normalize_targets(self) -> None:
        self.assertEqual(ide_task_bridge.normalize_target("CURSOR"), "cursor")
        self.assertEqual(ide_task_bridge.normalize_target("chatgpt"), "gemini")

    def test_unsupported_target(self) -> None:
        result = ide_task_bridge.dispatch_ide_task(
            title="x",
            body="y",
            target="vscode",
            dry_run=True,
        )
        self.assertFalse(result["ok"])

    def test_delivery_not_execution(self) -> None:
        store: ide_task_bridge.DispatchStore = {}
        result = ide_task_bridge.dispatch_ide_task(
            title="Probe",
            body="Hello",
            target="codex",
            correlation_id="corr-delivery-test",
            dry_run=True,
            store=store,
        )
        self.assertTrue(result["ok"])
        proj = result["execution_projection"]
        self.assertTrue(proj["delivered_to_inbox"])
        self.assertFalse(proj["running"])
        self.assertFalse(proj["completed"])
        self.assertEqual(proj["execution_state"], "delivered_to_inbox")

    def test_idempotent_dispatch(self) -> None:
        store: ide_task_bridge.DispatchStore = {}
        first = ide_task_bridge.dispatch_ide_task(
            title="Same",
            body="Body",
            target="cursor",
            correlation_id="corr-idem",
            dry_run=True,
            store=store,
        )
        second = ide_task_bridge.dispatch_ide_task(
            title="Same",
            body="Body",
            target="cursor",
            correlation_id="corr-idem",
            dry_run=True,
            store=store,
        )
        self.assertFalse(first.get("duplicate"))
        self.assertTrue(second.get("duplicate"))
        self.assertEqual(first["idempotency_key"], second["idempotency_key"])
        self.assertEqual(len(store), 1)

    def test_ops_progress_distinct_from_delivery(self) -> None:
        store: ide_task_bridge.DispatchStore = {}
        dispatched = ide_task_bridge.dispatch_ide_task(
            title="Run",
            body="Do",
            target="antigravity",
            correlation_id="corr-progress",
            dry_run=True,
            store=store,
        )
        key = dispatched["idempotency_key"]
        queued = dispatched["execution_projection"]["execution_state"]
        self.assertEqual(queued, "delivered_to_inbox")

        progressed = ide_task_bridge.mark_ops_progress(
            store=store,
            idempotency_key=key,
            ops_status="in_progress",
            a2a_state="working",
        )
        self.assertTrue(progressed["ok"])
        self.assertEqual(
            progressed["execution_projection"]["execution_state"],
            "running",
        )


if __name__ == "__main__":
    unittest.main()
