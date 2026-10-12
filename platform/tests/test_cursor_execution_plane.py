"""Cursor session liveness must not treat infrastructure heartbeats as IDE sessions."""
from __future__ import annotations

import unittest

from inneros_core_runtime import cursor_execution_plane as cep


class CursorExecutionPlaneTests(unittest.TestCase):
    def test_orchestrator_heartbeat_not_active_session(self) -> None:
        cep.register_session_heartbeat(source="cursor_ops_orchestrator", role="ops_executor")
        live = cep.read_session_liveness()
        self.assertFalse(live.get("active"))
        self.assertFalse(live.get("consumer_authentic"))

    def test_consumer_heartbeat_active_session(self) -> None:
        cep.register_cursor_consumer_heartbeat()
        live = cep.read_session_liveness()
        self.assertTrue(live.get("active"))
        self.assertTrue(live.get("consumer_authentic"))

    def test_classify_after_infra_heartbeat_not_partial(self) -> None:
        cep.register_session_heartbeat(source="cursor_ops_runner.claim", role="ops_executor")
        classified = cep.classify_cursor_execution()
        self.assertNotEqual(classified.get("execution_classification"), "partial")


if __name__ == "__main__":
    unittest.main()
