from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from inneros_core_runtime import a2a_bridge, a2a_oidc, google_adk_a2a
from inneros_core_runtime.tracking_envelope import (
    build_envelope,
    child_span,
    make_traceparent,
    parse_traceparent,
)


class FakeOps:
    def __init__(self) -> None:
        self.tasks: dict[str, dict] = {}
        self.seq = 0

    def create_task(self, **kwargs):
        self.seq += 1
        task_id = f"ops_fake_{self.seq}"
        task = {
            "task_id": task_id,
            "correlation_id": kwargs["correlation_id"],
            "assignee": kwargs["assignee"],
            "title": kwargs["title"],
            "status": "proposed",
            "evidence": {},
        }
        self.tasks[task_id] = task
        return {"ok": True, "created": True, "task_id": task_id, "task": task}

    def get_task(self, task_id):
        task = self.tasks.get(task_id)
        return dict(task) if task else None


class FakeStore:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    def put(self, record):
        self.records[record["a2a_task_id"]] = dict(record)

    def get(self, a2a_task_id):
        record = self.records.get(a2a_task_id)
        return dict(record) if record else None


class TrackingEnvelopeTests(unittest.TestCase):
    def test_traceparent_roundtrip_and_child_span(self) -> None:
        parent = make_traceparent()
        parsed = parse_traceparent(parent)
        self.assertIsNotNone(parsed)
        child = child_span(parent)
        child_parsed = parse_traceparent(child)
        self.assertEqual(parsed["trace_id"], child_parsed["trace_id"])
        self.assertNotEqual(parsed["span_id"], child_parsed["span_id"])

    def test_envelope_marks_quota_blocked_non_live(self) -> None:
        envelope = build_envelope(
            original_task_id="ops_365cfb128303",
            takeover_task_id="ops_8a6159731402",
            correlation_id="inneros-gemini-adk-cursor-takeover-20260828",
            quota_blocked=True,
            simulated=True,
        )
        self.assertEqual(envelope["live_mode"], "NON-LIVE")
        self.assertEqual(envelope["original_task_id"], "ops_365cfb128303")
        self.assertEqual(envelope["takeover_task_id"], "ops_8a6159731402")
        self.assertTrue(parse_traceparent(envelope["traceparent"]))


class OIDCNonLiveTests(unittest.TestCase):
    def test_mint_and_verify_hs256_service_token(self) -> None:
        token = a2a_oidc.mint_nonlive_service_token(audience="inneros-a2a", secret="test-secret")
        with patch.dict("os.environ", {"A2A_OIDC_HS256_SECRET": "test-secret", "A2A_OIDC_AUDIENCE": "inneros-a2a"}):
            claims = a2a_oidc.verify_service_token(token, audience="inneros-a2a")
        self.assertEqual(claims["aud"], "inneros-a2a")
        self.assertEqual(claims["live_mode"], "NON-LIVE")
        self.assertEqual(claims["verified_alg"], "HS256")

    def test_live_rs256_is_explicitly_pending(self) -> None:
        token = a2a_oidc.mint_nonlive_service_token()
        with patch.dict("os.environ", {"A2A_OIDC_LIVE": "yes"}):
            with self.assertRaises(a2a_oidc.A2AOIDCError) as ctx:
                a2a_oidc.verify_service_token(token)
        self.assertEqual(ctx.exception.code, "live_oidc_pending")


class RemoteA2aAgentContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bridge = a2a_bridge.A2ABridge(ops=FakeOps(), store=FakeStore())

    def test_existing_agent_cards_are_adk_sub_agents(self) -> None:
        catalog = google_adk_a2a.remote_a2a_agents()
        self.assertEqual(catalog["adk_pattern"], "RemoteA2aAgent")
        self.assertEqual(catalog["live_mode"], "NON-LIVE")
        for agent_id in a2a_bridge.AGENT_CARDS:
            self.assertIn(agent_id, catalog["sub_agents"])
            spec = catalog["sub_agents"][agent_id]
            self.assertEqual(spec["adk_class"], "RemoteA2aAgent")
            self.assertTrue(spec["agent_card_url"].endswith("agent-card.json"))
        self.assertIn("google-gemini", catalog["sub_agents"])
        self.assertTrue(catalog["sub_agents"]["google-gemini"]["metadata"]["quota_blocked"])

    def test_gemini_remote_dispatch_stays_non_live(self) -> None:
        result = google_adk_a2a.dispatch_remote_sub_agent(
            self.bridge,
            agent_id="google-gemini",
            title="Live invoke",
            body="Must not claim LIVE PASS",
            dry_run=False,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "gemini_quota_blocked")
        self.assertEqual(result["live_mode"], "NON-LIVE")

    def test_qwen_sub_agent_reuses_existing_a2a_bridge(self) -> None:
        result = google_adk_a2a.dispatch_remote_sub_agent(
            self.bridge,
            agent_id="qwen-coding",
            title="Implement contract",
            body="Reuse A2A/RACB. Do not duplicate IDE Task Bridge.",
            dry_run=False,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["adk_pattern"], "RemoteA2aAgent")
        self.assertEqual(result["live_mode"], "NON-LIVE")
        self.assertIn("traceparent", result["envelope"])
        self.assertEqual(result["ide_task_bridge"]["execution_state"], "delivered_to_inbox")
        self.assertTrue(result["ide_task_bridge"]["delivered_to_inbox"])
        self.assertFalse(result["ide_task_bridge"]["completed"])
        self.assertFalse(result["ide_task_bridge"]["duplicates_ide_bridge"])
        self.assertEqual(self.bridge.store.get(result["a2a_task_id"])["ops_task_id"], result["ops_task_id"])

    def test_ide_bridge_does_not_confuse_delivery_with_execution(self) -> None:
        submitted = google_adk_a2a.project_ide_task_bridge(
            a2a_status={"status": {"state": "submitted"}, "ops_status": "proposed"},
            target="cursor",
        )
        self.assertEqual(submitted["execution_state"], "delivered_to_inbox")
        running = google_adk_a2a.project_ide_task_bridge(
            a2a_status={"status": {"state": "working"}, "ops_status": "in_progress"},
            target="codex",
        )
        self.assertEqual(running["execution_state"], "running")
        done = google_adk_a2a.project_ide_task_bridge(
            a2a_status={"status": {"state": "completed"}, "ops_status": "completed"},
            target="gemini",
        )
        self.assertTrue(done["completed"])
        unsupported = google_adk_a2a.project_ide_task_bridge(target="vscode")
        self.assertEqual(unsupported["error"], "unsupported_ide")


if __name__ == "__main__":
    unittest.main()
