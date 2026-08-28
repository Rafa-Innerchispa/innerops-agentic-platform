import importlib
import importlib.util
import unittest


A2A_AVAILABLE = importlib.util.find_spec("a2a") is not None


@unittest.skipUnless(A2A_AVAILABLE, "a2a-sdk not installed in this test runtime")
class A2AServerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("raphiia_openai.a2a_server")
        cls.bridge = importlib.import_module("raphiia_openai.a2a_bridge")

    def test_all_five_agent_cards_are_protocol_1_0(self):
        self.assertEqual(len(self.bridge.AGENT_CARDS), 5)
        for agent_id in self.bridge.AGENT_CARDS:
            card = self.server.build_agent_card(agent_id)
            self.assertEqual(card.supported_interfaces[0].protocol_version, "1.0")
            self.assertEqual(card.supported_interfaces[0].protocol_binding, "JSONRPC")
            self.assertIn(f"/a2a/{agent_id}", card.supported_interfaces[0].url)
            self.assertTrue(card.skills)

    def test_multi_agent_app_exposes_rpc_and_agent_card_per_role(self):
        app = self.server.build_a2a_app()
        paths = {route.path for route in app.routes}
        self.assertIn("/status", paths)
        for agent_id in self.bridge.AGENT_CARDS:
            self.assertIn(f"/{agent_id}", paths)
            self.assertIn(f"/{agent_id}/.well-known/agent-card.json", paths)

    def test_delegation_does_not_call_complete(self):
        source = open(self.server.__file__, encoding="utf-8").read()
        self.assertNotIn("await updater.complete()", source)
        self.assertIn("Delegation is not completion", source)


if __name__ == "__main__":
    unittest.main()
