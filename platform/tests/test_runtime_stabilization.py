from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from raphiia_openai import dev_swarm_scheduler, local_execution_plane


class RuntimeStabilizationTests(unittest.TestCase):
    def test_live_verifier_task_is_filtered_from_dev_swarm(self):
        task = {
            "task_id": "ops_3b3a7ab9325d",
            "assignee": "gemini",
            "correlation_id": "gemini-live-verification-no-overlap-20260828",
            "title": "P0 Gemini live verifier",
        }
        self.assertTrue(dev_swarm_scheduler._is_live_verifier_ops_task(task))
        self.assertTrue(dev_swarm_scheduler._is_non_dev_ops_task(task))

    def test_scheduler_start_respects_enable_gate(self):
        with mock.patch.object(
            dev_swarm_scheduler,
            "_state",
            return_value={"enable_blocked": True, "enable_block_reason": "pre_guardian"},
        ):
            result = dev_swarm_scheduler.scheduler_start(dry_run=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "scheduler_enable_blocked")

    def test_fanout_does_not_auto_enable_scheduler(self):
        source = Path(dev_swarm_scheduler.fanout_execute.__code__.co_filename).read_text(encoding="utf-8")
        self.assertNotIn("scheduler_start(max_concurrent=max_workers", source)

    def test_innerops_platform_root_uses_python_unittest(self):
        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp)
            tests_dir = worktree / "platform" / "tests"
            tests_dir.mkdir(parents=True)
            (tests_dir / "test_smoke.py").write_text(
                "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            (worktree / "platform" / "inneros_core_runtime").mkdir(parents=True)
            with mock.patch.object(
                dev_swarm_scheduler,
                "_product_roots_for_repo",
                return_value=["platform"],
            ):
                commands = dev_swarm_scheduler._test_commands_for_policy(
                    dev_swarm_scheduler.SAFE_INNEROS_REPO,
                    worktree,
                    ["platform/inneros_core_runtime/foo.py"],
                )
        joined = [" ".join(command) for command in commands]
        self.assertTrue(any("unittest discover" in line for line in joined))
        self.assertFalse(any(line.startswith("npm ") for line in joined))

    def test_detect_test_profile_prefers_python_for_innerops_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "platform" / "inneros_core_runtime").mkdir(parents=True)
            (root / "package.json").write_text("{}", encoding="utf-8")
            self.assertEqual(local_execution_plane._detect_test_profile(root), "python-tests")


if __name__ == "__main__":
    unittest.main()
