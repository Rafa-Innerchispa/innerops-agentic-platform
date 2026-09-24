import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "inneros_core_runtime" / "agents" / "ag50_daily_companion.py"
SPEC = importlib.util.spec_from_file_location("ag50_worktree_test", MODULE_PATH)
ag50 = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(ag50)


class DailyCompanionTests(unittest.TestCase):
    def test_spoken_snapshot_prioritizes_real_ops_without_telemetry(self):
        live = {
            "current_priority": {
                "title": "Cerrar Alexa Guardian",
                "summary": "Completar integración física",
            },
            "open_ops_count": 2,
            "open_ops_tasks": [
                {"title": "Terminar VoiceOps", "status": "blocked", "priority": "p0"},
                {"title": "Cerrar GitLab", "status": "in_progress", "priority": "p0"},
            ],
        }
        text = ag50._spoken_snapshot(live, {"state": {}})
        self.assertIn("Cerrar Alexa Guardian", text)
        self.assertIn("Terminar VoiceOps", text)
        self.assertIn("Cerrar GitLab", text)
        self.assertNotIn("telemet", text.lower())

    def test_polish_falls_back_to_deterministic_snapshot(self):
        class Router:
            @staticmethod
            def run_local_model(**kwargs):
                return {"ok": False, "error": "offline"}

        spoken, result = ag50._polish_spoken_brief(
            "Prioridad principal: cerrar Alexa.",
            Router(),
        )
        self.assertEqual(spoken, "Prioridad principal: cerrar Alexa.")
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
