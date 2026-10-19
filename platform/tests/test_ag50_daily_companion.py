import importlib.util
import unittest
from datetime import datetime
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
            now=datetime(2026, 10, 19, 8, 0),
        )
        self.assertEqual(spoken, "Buenos días. Prioridad principal: cerrar Alexa.")
        self.assertFalse(result["ok"])

    def test_english_snapshot_is_voice_safe_for_large_counts(self):
        live = {
            "open_ops_count": 143,
            "open_ops_tasks": [
                {"title": "Finish Alexa demo", "status": "in_progress", "priority": "p0"},
            ],
        }
        text = ag50._spoken_snapshot(live, {"state": {}}, language="en-US")
        self.assertIn("more than one hundred", text)
        self.assertIn("Finish Alexa demo", text)
        self.assertNotIn("143", text)
        self.assertNotIn("Tienes", text)

    def test_english_evening_fallback_uses_local_time_greeting(self):
        class Router:
            @staticmethod
            def run_local_model(**kwargs):
                return {"ok": False, "error": "offline"}

        spoken, _ = ag50._polish_spoken_brief(
            "Main priority: restore the Alexa demo.",
            Router(),
            language="en-US",
            now=datetime(2026, 10, 19, 18, 0),
        )
        self.assertEqual(spoken, "Good evening. Main priority: restore the Alexa demo.")

    def test_spanish_greeting_is_not_hardcoded_to_morning(self):
        self.assertEqual(
            ag50._greeting("es-US", datetime(2026, 10, 19, 18, 0)),
            "Buenas noches",
        )


if __name__ == "__main__":
    unittest.main()
