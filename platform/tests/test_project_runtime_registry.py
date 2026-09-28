from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from raphiia_openai import project_runtime_registry as registry


def _git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return proc.stdout.strip()


class ProjectRuntimeRegistryBootstrapTests(unittest.TestCase):
    def _seed_project(self) -> tuple[tempfile.TemporaryDirectory[str], Path, str]:
        tmp = tempfile.TemporaryDirectory()
        core = Path(tmp.name) / "inneros_core"
        project = core / "workspaces" / "demo-runtime"
        project.mkdir(parents=True)
        _git(["init", "-b", "main"], project)
        _git(["config", "user.name", "Test"], project)
        _git(["config", "user.email", "test@example.invalid"], project)
        (project / "README.md").write_text("seed\n", encoding="utf-8")
        _git(["add", "README.md"], project)
        _git(["commit", "-m", "seed"], project)
        head = _git(["rev-parse", "HEAD"], project)
        return tmp, project, head

    def _register(self, project: Path) -> dict[str, object]:
        return registry.register_project(
            "demo-runtime",
            "Rafa-Innerchispa/demo-runtime",
            str(project),
            actor="test",
            source="unit-test",
        )

    def test_bootstrap_refuses_untracked_file_before_helper(self) -> None:
        tmp, project, _head = self._seed_project()
        self.addCleanup(tmp.cleanup)
        with patch.dict("os.environ", {"INNEROS_CORE_ROOT": str(Path(tmp.name) / "inneros_core")}, clear=False):
            self._register(project)
            (project / "scratch.txt").write_text("not committed\n", encoding="utf-8")
            with patch.object(registry, "_run_node", side_effect=AssertionError("helper must not run")):
                result = registry.bootstrap_runtime(
                    project_id="demo-runtime",
                    repo="Rafa-Innerchispa/demo-runtime",
                    base_ref="main",
                    dry_run=False,
                )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "dirty_project_runtime_preflight")
        self.assertEqual(result["dirty_paths"], [{"status": "??", "path": "scratch.txt"}])

    def test_bootstrap_refuses_tracked_modification_before_helper(self) -> None:
        tmp, project, _head = self._seed_project()
        self.addCleanup(tmp.cleanup)
        with patch.dict("os.environ", {"INNEROS_CORE_ROOT": str(Path(tmp.name) / "inneros_core")}, clear=False):
            self._register(project)
            (project / "README.md").write_text("dirty\n", encoding="utf-8")
            with patch.object(registry, "_run_node", side_effect=AssertionError("helper must not run")):
                result = registry.bootstrap_runtime(
                    project_id="demo-runtime",
                    repo="Rafa-Innerchispa/demo-runtime",
                    expected_sha="",
                    dry_run=False,
                )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "dirty_project_runtime_preflight")
        self.assertEqual(result["dirty_paths"], [{"status": "M", "path": "README.md"}])

    def test_bootstrap_clean_workspace_passes_expected_sha_to_helper(self) -> None:
        tmp, project, head = self._seed_project()
        self.addCleanup(tmp.cleanup)

        def fake_run_node(node: str, args: list[str], *, input_text: str = "", timeout: int = 120):
            payload = json.loads(input_text)
            self.assertEqual(payload["base_ref"], "main")
            self.assertEqual(payload["expected_sha"], head)
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps({"ok": True}), stderr="")

        with patch.dict("os.environ", {"INNEROS_CORE_ROOT": str(Path(tmp.name) / "inneros_core")}, clear=False):
            self._register(project)
            with patch.object(registry, "_run_node", side_effect=fake_run_node):
                result = registry.bootstrap_runtime(
                    project_id="demo-runtime",
                    repo="Rafa-Innerchispa/demo-runtime",
                    base_ref="main",
                    expected_sha=head,
                    dry_run=False,
                )
        self.assertTrue(result["ok"])
        self.assertEqual(result["postcheck"]["observed_sha"], head)
        self.assertFalse(result["postcheck"]["git_status"]["dirty"])

    def test_bootstrap_fails_expected_sha_mismatch_after_helper(self) -> None:
        tmp, project, _head = self._seed_project()
        self.addCleanup(tmp.cleanup)
        wrong_sha = "0" * 40
        with patch.dict("os.environ", {"INNEROS_CORE_ROOT": str(Path(tmp.name) / "inneros_core")}, clear=False):
            self._register(project)
            with patch.object(
                registry,
                "_run_node",
                return_value=subprocess.CompletedProcess(args=["helper"], returncode=0, stdout=json.dumps({"ok": True}), stderr=""),
            ):
                result = registry.bootstrap_runtime(
                    project_id="demo-runtime",
                    repo="Rafa-Innerchispa/demo-runtime",
                    expected_sha=wrong_sha,
                    dry_run=False,
                )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "expected_sha_mismatch")

    def test_bootstrap_fails_when_helper_leaves_dirty_checkout(self) -> None:
        tmp, project, _head = self._seed_project()
        self.addCleanup(tmp.cleanup)

        def dirtying_helper(*_args, **_kwargs):
            (project / "generated.txt").write_text("left behind\n", encoding="utf-8")
            return subprocess.CompletedProcess(args=["helper"], returncode=0, stdout=json.dumps({"ok": True}), stderr="")

        with patch.dict("os.environ", {"INNEROS_CORE_ROOT": str(Path(tmp.name) / "inneros_core")}, clear=False):
            self._register(project)
            with patch.object(registry, "_run_node", side_effect=dirtying_helper):
                result = registry.bootstrap_runtime(
                    project_id="demo-runtime",
                    repo="Rafa-Innerchispa/demo-runtime",
                    dry_run=False,
                )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "dirty_project_runtime_postcheck")
        self.assertEqual(result["dirty_paths"], [{"status": "??", "path": "generated.txt"}])


if __name__ == "__main__":
    unittest.main()
