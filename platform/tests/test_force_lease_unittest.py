from __future__ import annotations

import contextlib
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "inneros_core_runtime" / "local_execution_plane.py"
SPEC = importlib.util.spec_from_file_location("force_lease_local_execution_plane", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
lep = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lep)


class ForceWithLeaseFallbackTests(unittest.TestCase):
    def test_owner_fork_non_fast_forward_uses_exact_lease(self) -> None:
        branch = "chatgpt/fix/39708-cache-url-redaction"
        old_remote_sha = "5ace783e4cf4296247641bfa53b0ee7b616ae608"
        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp)
            calls: list[list[str]] = []

            @contextlib.contextmanager
            def fake_auth(url: str):
                yield {"GIT_TERMINAL_PROMPT": "0"}

            def fake_with_env(command, cwd, env, timeout_seconds=120, max_output_bytes=lep.MAX_OUTPUT_BYTES_DEFAULT):
                calls.append(command)
                if command[:3] == ["git", "ls-remote", "--heads"]:
                    return {"ok": True, "stdout": f"{old_remote_sha}\trefs/heads/{branch}\n", "stderr": "", "argv": command}
                if command[:2] == ["git", "push"] and command[2].startswith("--force-with-lease="):
                    return {"ok": True, "stdout": "", "stderr": "forced update", "argv": command}
                raise AssertionError(command)

            def fake_run(command, cwd, timeout_seconds=120, max_output_bytes=lep.MAX_OUTPUT_BYTES_DEFAULT):
                if command == ["git", "rev-parse", "--short", "HEAD"]:
                    return {"ok": True, "stdout": "3810a5936\n", "stderr": "", "argv": command}
                raise AssertionError(command)

            with mock.patch.object(lep, "_push_branch_without_lease", return_value={
                "ok": False,
                "push": {"ok": False, "stdout": "", "stderr": "! [rejected] non-fast-forward"},
            }), mock.patch.object(lep, "_repo_config", return_value={"profile": "go_gitlab_runner"}), mock.patch.object(
                lep, "_worktree_path", return_value=worktree
            ), mock.patch.object(
                lep,
                "_validate_remote_for_push",
                return_value={"ok": True, "remote": "origin", "url": "https://gitlab.com/rafagye/gitlab-runner.git"},
            ), mock.patch.object(lep, "_gitlab_push_auth_env", fake_auth), mock.patch.object(
                lep, "_run_with_env", side_effect=fake_with_env
            ), mock.patch.object(lep, "_run", side_effect=fake_run):
                result = lep.push_branch(
                    repo="gitlab-community/gitlab-org/gitlab-runner",
                    work_branch=branch,
                    actor="chatgpt",
                    task_id="ops_bafeb2978225",
                    correlation_id="gitlab-runner-39708-danger-fix-20260827",
                    idempotency_key="force-lease-test",
                    remote="origin",
                    dry_run=False,
                )

            self.assertTrue(result["ok"])
            self.assertTrue(result["force_with_lease_used"])
            self.assertEqual(result["remote_head_before"], old_remote_sha)
            self.assertEqual(
                calls[-1],
                [
                    "git",
                    "push",
                    f"--force-with-lease=refs/heads/{branch}:{old_remote_sha}",
                    "origin",
                    f"HEAD:refs/heads/{branch}",
                ],
            )

    def test_fallback_never_targets_upstream_remote(self) -> None:
        with mock.patch.object(lep, "_push_branch_without_lease", return_value={
            "ok": False,
            "push": {"ok": False, "stdout": "", "stderr": "! [rejected] non-fast-forward"},
        }):
            result = lep.push_branch(
                repo="gitlab-community/gitlab-org/gitlab-runner",
                work_branch="chatgpt/fix/39708-cache-url-redaction",
                actor="chatgpt",
                task_id="ops_bafeb2978225",
                correlation_id="gitlab-runner-39708-danger-fix-20260827",
                idempotency_key="no-upstream-force-test",
                remote="community",
                dry_run=False,
            )
        self.assertFalse(result["ok"])
        self.assertIsNot(result.get("force_with_lease_used"), True)


if __name__ == "__main__":
    unittest.main()
