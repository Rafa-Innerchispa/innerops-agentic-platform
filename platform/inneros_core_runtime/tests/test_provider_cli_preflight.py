import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Regression: tests for a worktree must exercise that worktree's platform code,
# not a stale canonical/runtime checkout that happens to be earlier on sys.path.
WORKTREE_PLATFORM = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKTREE_PLATFORM))
for module_name in list(sys.modules):
    if module_name == "inneros_core_runtime" or module_name.startswith("inneros_core_runtime."):
        sys.modules.pop(module_name, None)

from inneros_core_runtime import external_repair_worker
from inneros_core_runtime import provider_cli_preflight as preflight


class ProviderCliPreflightTests(unittest.TestCase):
    def test_imports_resolve_to_worktree_platform(self):
        self.assertTrue(str(Path(preflight.__file__).resolve()).startswith(str(WORKTREE_PLATFORM)))
        self.assertTrue(str(Path(external_repair_worker.__file__).resolve()).startswith(str(WORKTREE_PLATFORM)))

    def test_owner_scoped_codex_beats_system_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            cli = home / ".local" / "bin" / "codex"
            cli.parent.mkdir(parents=True)
            cli.write_text("#!/bin/sh\n", encoding="utf-8")
            cli.chmod(0o755)
            with patch("pathlib.Path.home", return_value=home):
                selected = preflight.canonical_cli("codex")
        self.assertEqual(selected, str(cli))

    def test_codex_login_status_failure_is_not_auth_ready(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False), \
            patch.object(preflight, "_run", return_value={"ok": False, "returncode": 1}):
            state = preflight.provider_auth_probe("codex", "/home/user/.local/bin/codex")
        self.assertFalse(state["auth_ready"])
        self.assertEqual(state["auth_failure_reason"], "codex_login_status_failed")
        self.assertTrue(state["auth_markers"]["codex_login_status_checked"])

    def test_auth_expired_failure_is_classified(self):
        failure = preflight.classify_provider_failure(
            stderr="HTTP 401 Unauthorized: Provided authentication token is expired. Please log out and sign in again."
        )
        self.assertEqual(failure, "auth_expired")

    def test_codex_argv_uses_canonical_preflight_cli(self):
        state = {
            "ok": True,
            "provider": "codex",
            "cli_path": "/home/user/.local/bin/codex",
            "auth_ready": True,
            "blocker": "",
        }
        with patch.object(preflight, "codex_preflight", return_value=state):
            argv, returned = external_repair_worker._codex_argv("do bounded work")
        self.assertEqual(argv[0], "/home/user/.local/bin/codex")
        self.assertEqual(argv[1:3], ["exec", "--full-auto"])
        self.assertEqual(returned["cli_path"], argv[0])

    def test_worker_blocks_before_subprocess_when_auth_not_ready(self):
        blocked = {
            "ok": False,
            "provider": "codex",
            "cli_path": "/home/user/.local/bin/codex",
            "auth_ready": False,
            "blocker": "auth_not_ready",
        }
        fake_collection = MagicMock()
        fake_db = {"ralfia_external_repair_runs": fake_collection}
        with patch.object(preflight, "codex_preflight", return_value=blocked), \
            patch.object(external_repair_worker.external_repair_agent, "_db", return_value=fake_db), \
            patch.object(external_repair_worker.external_repair_agent, "complete_external_repair_run") as complete, \
            patch.object(external_repair_worker.subprocess, "run") as run:
            external_repair_worker._runner("run_fixture", "codex", "/tmp", "prompt", 60)
        run.assert_not_called()
        fake_collection.update_one.assert_called_once()
        kwargs = complete.call_args.kwargs
        self.assertEqual(kwargs["outcome"], "blocked")
        self.assertEqual(kwargs["result"], "BLOCKED")
        self.assertEqual(kwargs["evidence"]["failure_class"], "auth_not_ready")

    def test_worker_turns_401_into_nonchargeable_blocker(self):
        ready = {
            "ok": True,
            "provider": "codex",
            "cli_path": "/home/user/.local/bin/codex",
            "auth_ready": True,
            "blocker": "",
        }
        proc = SimpleNamespace(returncode=1, stdout="", stderr="401 Unauthorized token_expired")
        fake_collection = MagicMock()
        fake_db = {"ralfia_external_repair_runs": fake_collection}
        with patch.object(preflight, "codex_preflight", return_value=ready), \
            patch.object(external_repair_worker.external_repair_agent, "_db", return_value=fake_db), \
            patch.object(external_repair_worker.external_repair_agent, "checkpoint_external_repair_run"), \
            patch.object(external_repair_worker.external_repair_agent, "complete_external_repair_run") as complete, \
            patch.object(external_repair_worker.subprocess, "run", return_value=proc) as run:
            external_repair_worker._runner("run_fixture", "codex", "/tmp", "prompt", 60)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][0], "/home/user/.local/bin/codex")
        fake_collection.update_one.assert_called_once()
        kwargs = complete.call_args.kwargs
        self.assertEqual(kwargs["outcome"], "blocked")
        self.assertEqual(kwargs["result"], "BLOCKED")
        self.assertEqual(kwargs["evidence"]["failure_class"], "auth_expired")


if __name__ == "__main__":
    unittest.main()
