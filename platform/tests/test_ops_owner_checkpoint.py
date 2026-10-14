"""Checkpoint owner delivery (ChatGPT durable + WhatsApp hook)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from inneros_core_runtime import ops_owner_checkpoint as ocp


class OpsOwnerCheckpointTests(unittest.TestCase):
    def test_publish_includes_task_id_and_ack_is_not_done(self) -> None:
        task = {
            "task_id": "ops_e82d4a60d52e",
            "title": "InnerOS ops checkpoint",
            "correlation_id": "inneros-p0",
            "execution_lane": "local_dev_swarm",
            "revision": 3,
        }
        with (
            patch.object(ocp, "NOTIFY_CHECKPOINT", True),
            patch(
                "inneros_core_runtime.durable_coordination_spine.create_durable_message",
                return_value={"ok": True, "message_id": "msg_test", "persisted": True},
            ) as durable,
            patch(
                "inneros_core_runtime.notifications.ops_task_alerts.notify_ops_transition",
                return_value={"ok": True},
            ),
        ):
            out = ocp.publish_ops_owner_checkpoint(
                task,
                phase="verification",
                evidence={"commit_sha": "a" * 40, "test_results": {"exit_code": 0}},
                actor="cursor",
            )
        self.assertTrue(out["ok"])
        durable.assert_called_once()
        call = durable.call_args.kwargs
        self.assertEqual(call["task_id"], "ops_e82d4a60d52e")
        self.assertIn("ops_e82d4a60d52e", call["content"])
        self.assertIn("ACK de entrega NO es DONE", call["content"])
        self.assertEqual(call["metadata"]["execution_phase"], "verification")
        self.assertFalse(call["metadata"]["terminal"])


if __name__ == "__main__":
    unittest.main()
