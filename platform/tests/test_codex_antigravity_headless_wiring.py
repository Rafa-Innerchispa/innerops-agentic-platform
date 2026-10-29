from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from inneros_core_runtime import interactive_provider_bounded_executor as ipbe
from inneros_core_runtime import ops_model_execution_journal as omj


class CodexAntigravityWiringTests(unittest.TestCase):
    def test_innocuous_canary_requires_authenticated_payload(self) -> None:
        loose = {"title": "canary", "objective": "write docs/CODEX_CANARY.md only"}
        self.assertFalse(ipbe.is_innocuous_canary_task(loose, "codex"))
        signed = {
            "objective": "canary",
            "payload": {
                "provider_canary": "codex",
                "execution_mode": "SYNTHETIC_CANARY",
            },
        }
        self.assertTrue(ipbe.is_innocuous_canary_task(signed, "codex"))
        self.assertFalse(ipbe.is_innocuous_canary_task(signed, "antigravity"))

    def test_codex_headless_script_invokes_bounded_executor(self) -> None:
        script = PLATFORM_DIR / "scripts" / "codex_ops_headless_execute_one.py"
        spec = importlib.util.spec_from_file_location("codex_ops_headless_execute_one", script)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        task = {"task_id": "ops_codex_wire", "claim_token": "tok", "assignee": "codex"}
        col = MagicMock()
        col.find_one.return_value = task
        db = MagicMock()
        db.__getitem__.return_value = col
        with patch.object(sys, "argv", ["codex_ops_headless_execute_one.py", "ops_codex_wire"]):
            with patch.object(mod.mongo_store, "get_db", return_value=db):
                with patch.object(
                    mod.ipbe,
                    "execute_claimed_task",
                    return_value={"ok": False, "error": "blocked_execution_not_wired"},
                ) as execute:
                    with patch.object(sys, "stdout", io.StringIO()):
                        rc = mod.main()
        self.assertEqual(rc, 1)
        execute.assert_called_once_with("ops_codex_wire", "codex")

    def test_model_journal_append(self) -> None:
        col = MagicMock()
        db = MagicMock()
        db.__getitem__.return_value = col
        with patch.object(omj.mongo_store, "get_db", return_value=db):
            out = omj.record_model_execution(
                "ops_journal_probe",
                provider="codex",
                configured_model="gpt-5.6-sol",
                resolved_model=None,
                model_source="test",
            )
        self.assertTrue(out.get("ok"))
        col.update_one.assert_called_once()

    def test_bounded_canary_marker_helper_writes_file(self) -> None:
        from inneros_core_runtime import temporal_bounded_executor as tbe

        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp)
            envelope = {
                "task_id": "ops_canary_local",
                "correlation_id": "ops_canary_local",
                "required_objective_paths": ["docs/CODEX_CANARY.md"],
                "objective": "docs/CODEX_CANARY.md innocuous canary",
            }
            written = tbe._apply_required_objective_markers(envelope, wt)
            self.assertIn("docs/CODEX_CANARY.md", written)
            self.assertTrue((wt / "docs" / "CODEX_CANARY.md").is_file())


if __name__ == "__main__":
    unittest.main()
