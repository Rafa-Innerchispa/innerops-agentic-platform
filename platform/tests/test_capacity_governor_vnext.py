import unittest
from pathlib import Path

from raphiia_openai import capacity_governor_vnext
from raphiia_openai import dev_swarm_scheduler


class CapacityGovernorVNextTests(unittest.TestCase):
    def test_authorized_baseline_does_not_block_workers(self):
        status = capacity_governor_vnext.classify_capacity(
            cpu_load_ratio=0.20,
            ram_used_ratio=0.35,
            vram_used_ratio=0.82,
            baseline_vram_ratio=0.82,
            active_worker_count=0,
            sustained_samples=3,
        )
        self.assertEqual(status["state"], capacity_governor_vnext.BASELINE)
        self.assertEqual(status["budget"]["recommended_workers"], 4)
        self.assertTrue(status["budget"]["baseline_does_not_count_as_worker"])

    def test_brief_cpu_spike_is_observed_not_throttled(self):
        status = capacity_governor_vnext.classify_capacity(
            cpu_load_ratio=0.90,
            ram_used_ratio=0.40,
            active_worker_count=0,
            sustained_samples=1,
        )
        self.assertGreater(status["budget"]["recommended_workers"], 0)
        self.assertIn("cpu_spike_observed_no_throttle", status["observations"])

    def test_unknown_orphan_vram_is_anomaly(self):
        status = capacity_governor_vnext.classify_capacity(
            cpu_load_ratio=0.20,
            ram_used_ratio=0.35,
            vram_used_ratio=0.98,
            baseline_vram_ratio=0.0,
            unknown_vram_ratio=0.85,
            active_worker_count=0,
            sustained_samples=3,
        )
        self.assertEqual(status["state"], capacity_governor_vnext.ANOMALY)
        self.assertEqual(status["budget"]["recommended_workers"], 0)
        self.assertIn("unknown_vram_high", status["reasons"])

    def test_non_baseline_ollama_model_is_workload(self):
        self.assertEqual(
            capacity_governor_vnext.classify_process("ollama", "neural-chat:7b"),
            capacity_governor_vnext.WORKLOAD,
        )
        self.assertEqual(
            capacity_governor_vnext.classify_process("ollama", "qwen2.5vl:7b"),
            capacity_governor_vnext.BASELINE,
        )

    def test_scheduler_no_longer_uses_safe_id_query_gate(self):
        source = Path("inneros_core_runtime/dev_swarm_scheduler.py").read_text(encoding="utf-8")
        self.assertNotIn('"task_id": {"$in": list(CURRENT_SAFE_TASK_IDS)}', source)
        self.assertIn('"admission_policy": "repo_policy_priority_capacity"', source)

    def test_policy_based_dual_node_admission_fixture(self):
        original = dev_swarm_scheduler.local_execution_plane.repo_policy_status
        try:
            dev_swarm_scheduler.local_execution_plane.repo_policy_status = lambda repo: {
                "ok": True,
                "write_scope": "branch",
                "policy": {"source_path": "/tmp/source", "worktrees_path": "/tmp/worktrees"},
            }
            ok, reason, repo = dev_swarm_scheduler._eligible_reason(
                {
                    "task_id": "ops_policy_fixture",
                    "status": "proposed",
                    "priority": "p0",
                    "assignee": "codex",
                    "tags": ["dev_swarm_fixture"],
                    "title": "Policy fixture for dual-node admission",
                    "checklist": ["No production"],
                }
            )
        finally:
            dev_swarm_scheduler.local_execution_plane.repo_policy_status = original
        self.assertTrue(ok)
        self.assertEqual(reason, "eligible")
        self.assertEqual(repo, dev_swarm_scheduler.SAFE_INNEROS_REPO)


if __name__ == "__main__":
    unittest.main()
