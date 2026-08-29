import importlib
import importlib.util
import sys
import unittest
from pathlib import Path


PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

A2A_AVAILABLE = importlib.util.find_spec("a2a") is not None
SPECIAL_CARDS = {
    "inneros-orchestrator",
    "qwen-coding",
    "codex-repair",
    "integration-guardian",
    "browser-qa",
}


@unittest.skipUnless(A2A_AVAILABLE, "a2a-sdk not installed in this test runtime")
class A2AServerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("raphiia_openai.a2a_server")
        cls.bridge = importlib.import_module("raphiia_openai.a2a_bridge")
        cls.catalog = importlib.import_module("raphiia_openai.agents.agent_catalog")

    def test_merged_registry_contains_every_functional_catalog_agent(self):
        functional = self.catalog.get_agent_catalog(functional_only=True).get("agents") or []
        functional_ids = {str(item["agent_id"]).upper() for item in functional}
        cards = self.bridge._all_cards()
        self.assertTrue(functional_ids)
        self.assertTrue(functional_ids.issubset(cards.keys()))
        self.assertTrue(SPECIAL_CARDS.issubset(cards.keys()))
        self.assertEqual(len(cards), len(functional_ids) + len(SPECIAL_CARDS))
        self.assertIn("AG-52", functional_ids)
        self.assertIn("AG-52", cards)
        self.assertEqual(cards["AG-52"]["metadata"]["agent_id"], "AG-52")
        self.assertTrue(cards["AG-52"]["metadata"]["local_first"])

    def test_every_merged_card_builds_as_a2a_protocol_1_0(self):
        cards = self.bridge._all_cards()
        for agent_id in cards:
            card = self.server.build_agent_card(agent_id, cards=cards)
            self.assertEqual(card.supported_interfaces[0].protocol_version, "1.0")
            self.assertEqual(card.supported_interfaces[0].protocol_binding, "JSONRPC")
            self.assertIn(f"/a2a/{agent_id}", card.supported_interfaces[0].url)
            self.assertTrue(card.skills)

    def test_multi_agent_app_exposes_rpc_and_agent_card_for_merged_registry(self):
        cards = self.bridge._all_cards()
        app = self.server.build_a2a_app()
        paths = [route.path for route in app.routes]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertIn("/status", paths)
        for agent_id in cards:
            self.assertIn(f"/{agent_id}", paths)
            self.assertIn(f"/{agent_id}/.well-known/agent-card.json", paths)

    def test_catalog_agent_executor_is_accepted(self):
        executor = self.server.InnerOSA2AExecutor("AG-52")
        self.assertEqual(executor.agent_id, "AG-52")

    def test_dry_run_dispatch_is_submitted_not_completed(self):
        result = self.bridge.dispatch(
            agent_id="AG-52",
            title="A2A card smoke",
            body="Verify AG-52 can be addressed through the merged registry.",
            correlation_id="test-a2a-agentcard-ag52",
            dry_run=True,
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["agent_id"], "AG-52")
        self.assertEqual(result["state"], "submitted")
        self.assertNotEqual(result["state"], "completed")

    def test_delegation_does_not_call_complete(self):
        source = open(self.server.__file__, encoding="utf-8").read()
        self.assertNotIn("await updater.complete()", source)
        self.assertIn("Delegation is not completion", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
