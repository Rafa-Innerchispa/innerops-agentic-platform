"""Bounded AG-59 DMX capability adapter tests, offline only."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import importlib.util
import os

# Worktree has a top-level directory named 'platform' that shadows stdlib.
# Load the real stdlib module before importing capability_gateway/uuid.
_stdlib_platform_file = Path(os.__file__).resolve().parent / "platform.py"
_stdlib_platform_spec = importlib.util.spec_from_file_location("platform", _stdlib_platform_file)
_stdlib_platform_module = importlib.util.module_from_spec(_stdlib_platform_spec)
sys.modules["platform"] = _stdlib_platform_module
_stdlib_platform_spec.loader.exec_module(_stdlib_platform_module)

# Run from repository root without relying on a globally installed package.
PROJECT_PLATFORM = Path(__file__).resolve().parents[1]
if str(PROJECT_PLATFORM) not in sys.path:
    sys.path.insert(0, str(PROJECT_PLATFORM))

from inneros_core_runtime import capability_gateway as gateway


class TestHomeDmxCapability(unittest.TestCase):
    def test_discovery_and_scopes(self):
        ids = {c["capability_id"] for c in gateway.capability_search(query="dmx")["capabilities"]}
        self.assertIn("home.dmx.status.v1", ids)
        self.assertIn("home.dmx.set_scene.v1", ids)
        status = gateway.capability_describe("home.dmx.status.v1")["capability"]
        color = gateway.capability_describe("home.dmx.set_scene.v1")["capability"]
        self.assertEqual(status["mode"], "read_only")
        self.assertEqual(status["required_scopes"], ["ralfia:read"])
        self.assertEqual(color["mode"], "mutation")
        self.assertEqual(color["required_scopes"], ["ralfia:write"])

    def test_status_delegates_without_changes(self):
        from inneros_core_runtime.agents import ag59_dmx_artnet_orchestrator as dmx
        with patch.object(dmx, "dmx_status", return_value={"ok": True, "current_scene": "rainbow"}) as getter:
            result = gateway.capability_invoke("home.dmx.status.v1", {})
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["current_scene"], "rainbow")
        getter.assert_called_once_with()

    def test_targeted_colors_never_broadcast(self):
        from inneros_core_runtime.agents import ag59_dmx_artnet_orchestrator as dmx
        with patch.object(dmx, "dmx_set_scene", return_value={"ok": True, "verified_backend_ack": True}) as setter:
            for target in ("pulpos", "tachos"):
                result = gateway.capability_invoke(
                    "home.dmx.set_scene.v1",
                    {"target": target, "color": "azul", "brightness": 190},
                )
                self.assertTrue(result["ok"])
            self.assertEqual(setter.call_count, 2)
            self.assertEqual(setter.call_args_list[0].kwargs["target"], "pulpos")
            self.assertEqual(setter.call_args_list[1].kwargs["target"], "tachos")

    def test_global_addressing_and_bad_brightness_rejected(self):
        from inneros_core_runtime.agents import ag59_dmx_artnet_orchestrator as dmx
        with patch.object(dmx, "dmx_set_scene") as setter:
            for target in ("all", "todas", "universe_1", ""):
                result = gateway.capability_invoke(
                    "home.dmx.set_scene.v1", {"target": target, "color": "azul"}
                )
                self.assertFalse(result["ok"])
            self.assertFalse(gateway.capability_invoke(
                "home.dmx.set_scene.v1",
                {"target": "pulpos", "color": "azul", "brightness": 0}
            )["ok"])
            self.assertFalse(gateway.capability_invoke(
                "home.dmx.set_scene.v1",
                {"target": "pulpos", "scene": "frenzy"}
            )["ok"])
            setter.assert_not_called()

    def test_read_only_mode_fails_closed(self):
        from inneros_core_runtime.agents import ag59_dmx_artnet_orchestrator as dmx
        with patch.object(dmx, "dmx_set_scene") as setter:
            result = gateway.capability_invoke(
                "home.dmx.set_scene.v1",
                {"target": "pulpos", "color": "azul"},
                context={"enforce_read_only": True},
            )
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "MUTATION_FORBIDDEN_IN_READ_ONLY_MODE")
            setter.assert_not_called()


if __name__ == "__main__":
    unittest.main()
