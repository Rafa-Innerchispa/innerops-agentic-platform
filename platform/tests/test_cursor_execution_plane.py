"""Cursor session liveness must not treat infrastructure heartbeats as IDE sessions."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from inneros_core_runtime import cursor_execution_plane as cep


class CursorExecutionPlaneTests(unittest.TestCase):
    def test_orchestrator_heartbeat_not_active_session(self) -> None:
        cep.register_session_heartbeat(source="cursor_ops_orchestrator", role="ops_executor")
        live = cep.read_session_liveness()
        self.assertFalse(live.get("active"))
        self.assertFalse(live.get("consumer_authentic"))

    def test_consumer_heartbeat_does_not_activate_ide_session(self) -> None:
        cep.register_cursor_consumer_heartbeat()
        live = cep.read_session_liveness()
        consumer = cep.read_inbox_consumer_liveness()
        self.assertFalse(live.get("active"))
        self.assertTrue(consumer.get("active"))

    def test_ide_session_register_enables_execute(self) -> None:
        cep.register_cursor_ide_session()
        live = cep.read_session_liveness()
        self.assertTrue(live.get("active"))

    def test_authenticated_sdk_is_headless_ready_even_without_cli_or_ide(self) -> None:
        sdk = {
            "ready": True, "installed": True, "auth_ready": True,
            "enabled": True, "host_eligible": True,
        }
        with (
            patch.object(cep, "probe_mcp_bridge", return_value={"reachable": True}),
            patch.object(cep, "read_session_liveness", return_value={"active": False}),
            patch.object(cep, "read_inbox_consumer_liveness", return_value={"active": True}),
        ):
            classified = cep.classify_cursor_execution(
                cli_probe={"installed": False, "headless_supported": False, "auth_ready": False},
                sdk_probe=sdk,
            )
        self.assertEqual(classified["execution_classification"], "headless_ready")
        self.assertEqual(classified["transport"], "local_cursor_sdk_headless")
        self.assertTrue(classified["headless_ready"])
        self.assertNotIn("no_active_cursor_ide_session", classified["blockers"])
        self.assertTrue(classified["sdk_probe_summary"]["ready"])
        self.assertNotIn("key", str(classified["sdk_probe_summary"]).lower())

    def test_missing_sdk_auth_never_treats_inbox_ack_as_execution(self) -> None:
        for missing in ("installed", "auth_ready", "enabled", "host_eligible"):
            with self.subTest(missing=missing):
                sdk = {
                    "ready": True, "installed": True, "auth_ready": True,
                    "enabled": True, "host_eligible": True,
                }
                sdk[missing] = False
                with (
                    patch.object(cep, "probe_mcp_bridge", return_value={"reachable": True}),
                    patch.object(cep, "read_session_liveness", return_value={"active": False}),
                    patch.object(cep, "read_inbox_consumer_liveness", return_value={"active": True}),
                ):
                    classified = cep.classify_cursor_execution(
                        cli_probe={"installed": False},
                        sdk_probe=sdk,
                    )
                self.assertEqual(classified["execution_classification"], "remote_inbox_only")
                self.assertFalse(classified["headless_ready"])
                self.assertIn("inbox_consumer_active_but_ide_session_required_for_execute",
                              classified["blockers"])

    def test_sdk_disabled_and_no_ide_is_delivery_only(self) -> None:
        with (
            patch.object(cep, "probe_cursor_sdk_readiness", return_value={
                "ready": False, "installed": True, "auth_ready": True,
                "enabled": False, "host_eligible": True,
            }),
            patch.object(cep, "probe_mcp_bridge", return_value={"reachable": True}),
            patch.object(cep, "read_session_liveness", return_value={"active": False}),
            patch.object(cep, "read_inbox_consumer_liveness", return_value={"active": True}),
        ):
            classified = cep.classify_cursor_execution()
        self.assertEqual(classified["execution_classification"], "remote_inbox_only")

    def test_classify_after_infra_heartbeat_not_partial(self) -> None:
        cep.register_session_heartbeat(source="cursor_ops_runner.claim", role="ops_executor")
        classified = cep.classify_cursor_execution()
        self.assertNotEqual(classified.get("execution_classification"), "partial")


if __name__ == "__main__":
    unittest.main()
