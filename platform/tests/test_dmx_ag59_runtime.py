from pathlib import Path
import ast
import sys
import unittest
from unittest.mock import patch

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from raphiia_openai import a2a_agent_registry
from raphiia_openai.agents import agent_catalog
from raphiia_openai.agents import ag59_dmx_artnet_orchestrator as ag59
from raphiia_openai.agents.pool_agent_runners import get_runner_registry


class DMXAG59RuntimeTests(unittest.TestCase):
    def test_agent_id_is_collision_free_and_runnable(self):
        self.assertIn("DMX", agent_catalog.AGENT_CATALOG["AG-59"]["display_name"])
        self.assertEqual(agent_catalog.AGENT_CATALOG["AG-59"]["domain"], "home")
        self.assertEqual(
            set(agent_catalog.AGENT_CATALOG["AG-59"].get("mcp_tools") or []),
            {"dmx_status", "dmx_set_scene", "dmx_blackout"},
        )
        self.assertIn("AG-59", get_runner_registry())
        self.assertNotEqual(agent_catalog.AGENT_CATALOG["AG-59"]["display_name"], "Backlog Steward")

    def test_ag32_remains_master_mult_protocol_parent(self):
        self.assertEqual(agent_catalog.AGENT_CATALOG["AG-32"]["domain"], "home")
        self.assertIn("home assistant", agent_catalog.AGENT_CATALOG["AG-32"]["aliases"])
        self.assertIn("hubitat", agent_catalog.AGENT_CATALOG["AG-32"]["intent_keywords"])

    def test_status_is_sanitized(self):
        raw = {
            "ok": True,
            "status": "online",
            "target_ip": "10.0.0.10",
            "universe": 1,
            "current_effect": "rainbow",
            "running": True,
        }
        with patch.object(ag59, "_request_json", return_value=raw):
            result = ag59.dmx_status()
        self.assertTrue(result["ok"])
        self.assertEqual(result["current_scene"], "rainbow")
        self.assertNotIn("target_ip", result)
        self.assertNotIn("universe", result)
        self.assertNotIn("10.0.0.10", str(result))

    def test_scene_allowlist_maps_marketing_aliases(self):
        calls = []

        def fake_request(method, path, payload=None):
            calls.append((method, path, payload))
            return {"ok": True}

        with patch.object(ag59, "_request_json", side_effect=fake_request):
            purple = ag59.dmx_set_scene("morado UV")
            red = ag59.dmx_set_scene("rojo sangre")
            rainbow = ag59.dmx_set_scene("rainbow")

        self.assertEqual(purple["scene"], "morado_uv")
        self.assertEqual(red["scene"], "rojo_sangre")
        self.assertEqual(rainbow["scene"], "rainbow")
        self.assertEqual(calls[0][1], "/api/color")
        self.assertEqual(calls[0][2]["target"], "todas")
        self.assertEqual(calls[2][1], "/api/scene")

    def test_color_target_request_is_bounded_and_sanitized(self):
        calls = []

        def fake_request(method, path, payload=None):
            calls.append((method, path, payload))
            return {"ok": True}

        with patch.object(ag59, "_request_json", side_effect=fake_request):
            result = ag59.dmx_set_scene("", color="cyan", target="tachos", brightness=999)

        self.assertTrue(result["ok"])
        self.assertEqual(result["scene"], "cian")
        self.assertEqual(result["target"], "tachos")
        self.assertEqual(calls[0][1], "/api/color")
        self.assertEqual(calls[0][2], {"color": "cian", "target": "tachos", "brightness": 255})

    def test_voice_color_alias_morado_uv_maps_to_physical_color(self):
        calls = []

        def fake_request(method, path, payload=None):
            calls.append((method, path, payload))
            return {"ok": True}

        with patch.object(ag59, "_request_json", side_effect=fake_request):
            result = ag59.dmx_set_scene("", color="morado_uv", target="tachos", brightness=180)

        self.assertTrue(result["ok"])
        self.assertEqual(result["scene"], "morado")
        self.assertEqual(result["target"], "tachos")
        self.assertEqual(calls[0][2], {"color": "morado", "target": "tachos", "brightness": 180})

    def test_unknown_target_fails_closed_without_backend_call(self):
        with patch.object(ag59, "_request_json") as backend:
            result = ag59.dmx_set_scene("", color="rojo", target="channel_1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "unsupported_target")
        backend.assert_not_called()

    def test_unsupported_scene_fails_closed_without_backend_call(self):
        with patch.object(ag59, "_request_json") as backend:
            result = ag59.dmx_set_scene("channel 1 full")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "unsupported_scene")
        backend.assert_not_called()

    def test_casual_text_never_changes_physical_state(self):
        with patch.object(ag59, "_request_json") as backend:
            result = ag59.run_dmx_orchestrator("hello, how are you?", dry_run=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "none")
        backend.assert_not_called()

    def test_a2a_projection_contains_ag59(self):
        cards = a2a_agent_registry.merged_agent_cards({}, "1.0", "test")
        self.assertIn("AG-59", cards)
        self.assertEqual(cards["AG-59"]["metadata"]["domain"], "home")
        self.assertTrue(cards["AG-59"]["metadata"]["local_first"])

    def test_mcp_surface_declares_only_safe_high_level_dmx_tools(self):
        source = (PLATFORM_ROOT / "inneros_core_runtime" / "mcp_server.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        self.assertTrue({"dmx_status", "dmx_set_scene", "dmx_blackout"}.issubset(functions))
        self.assertNotIn("dmx_set_channel", functions)
        self.assertNotIn("dmx_set_universe", functions)


if __name__ == "__main__":
    unittest.main()
