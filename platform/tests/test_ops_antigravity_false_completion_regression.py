"""Regression: ops_64d4bf6d941e false COMPLETED via text-only Antigravity Gemini API."""
from __future__ import annotations

import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path

from inneros_core_runtime import ops_completion_policy as ocp
from inneros_core_runtime import temporal_activities as ta
from inneros_core_runtime.execution_receipts import git_head

NEBius_SHA = "b90b8e0781b6ddbe4dfdb0ecf57071396000682c"
REGRESSION_TASK = {
    "task_id": "ops_64d4bf6d941e",
    "task_class": "coding",
    "title": "Hosting pcdoctor.ai / pcdoctor.com.ec",
    "objective": "Deploy landing WordPress cPanel hosting allowlist pcdoctor.ai pcdoctor.com.ec",
    "repo": "Rafa-Innerchispa/innerops-agentic-platform",
}


def _intel_log_evidence() -> dict:
    return {
        "headless_primary": "antigravity_gemini_api",
        "pinned_model_policy": "gemini-3.7-flash-medium",
        "gemini_model": "gemini-3.6-flash",
        "summary": "Plan ejecutado en InnerOS (Antigravity)",
        "notes": "antigravity_headless_execute_one",
        "objective_files_count": 1,
        "objective_paths": ["platform/docs/ANTIGRAVITY_HEADLESS_64d4bf6d941e.md"],
        "commit_sha": NEBius_SHA,
        "test_results": {},
        "code_diff": "",
    }


class AntigravityFalseCompletionRegressionTests(unittest.TestCase):
    def test_text_only_headless_evidence_rejected(self) -> None:
        err = ocp.validate_mutating_completion_evidence(REGRESSION_TASK, _intel_log_evidence())
        self.assertIsNotNone(err)
        self.assertIn("text_only", err)

    def test_empty_test_results_rejected(self) -> None:
        ev = dict(_intel_log_evidence())
        ev.pop("headless_primary")
        plain_coding = {"task_class": "coding", "objective": "fix unit test in platform module"}
        err = ocp.validate_mutating_completion_evidence(plain_coding, ev)
        self.assertIsNotNone(err)
        self.assertIn("exit_code", err)

    def test_deployment_objective_requires_host_mutation(self) -> None:
        ev = {
            "commit_sha": NEBius_SHA,
            "objective_paths": ["platform/docs/x.md"],
            "objective_files_count": 1,
            "test_results": {"exit_code": 0, "ok": True},
        }
        err = ocp.validate_mutating_completion_evidence(REGRESSION_TASK, ev)
        self.assertEqual(err, "deployment_requires_observed_host_mutation")

    def test_temporal_gate_rejects_intel_log_agent_result(self) -> None:
        agent = {
            **_intel_log_evidence(),
            "completion_channel": "antigravity_interactive",
            "ok": True,
        }
        gate = asyncio.run(ta.activity_validate_completion_gate(REGRESSION_TASK, agent))
        self.assertFalse(gate["passed"])
        err_l = gate["error"].lower()
        self.assertTrue("text_only" in err_l or "host/deployment" in err_l or "deployment" in err_l)

    def test_temporal_gate_rejects_intel_log_without_interactive_channel(self) -> None:
        """Bounded Temporal path must not accept SHA+paths without receipt (ops_64d4bf6d941e drift)."""
        agent = {
            **_intel_log_evidence(),
            "test_results": {"exit_code": 0, "ok": True},
            "ok": True,
        }
        gate = asyncio.run(ta.activity_validate_completion_gate(REGRESSION_TASK, agent))
        self.assertFalse(gate["passed"])
        err_l = gate["error"].lower()
        self.assertTrue(
            "text_only" in err_l or "deployment" in err_l or "host" in err_l or "exit_code" in err_l,
            msg=gate.get("error"),
        )

    def test_temporal_gate_rejects_text_only_on_plain_coding(self) -> None:
        agent = {
            "headless_primary": "antigravity_gemini_api",
            "commit_sha": NEBius_SHA,
            "objective_paths": ["x.py"],
            "objective_files_count": 1,
            "test_results": {"exit_code": 0, "ok": True},
            "completion_channel": "antigravity_interactive",
        }
        env = {"task_class": "coding", "objective": "patch helper"}
        gate = asyncio.run(ta.activity_validate_completion_gate(env, agent))
        self.assertFalse(gate["passed"])
        err_l = gate["error"].lower()
        self.assertTrue("text_only" in err_l or "text-only" in err_l)

    def test_runtime_gemini_model_mismatch_rejected_on_complete(self) -> None:
        from inneros_core_runtime import interactive_ops_runner as ior
        from unittest.mock import MagicMock, patch

        task = {
            "task_id": "ops_model_mismatch",
            "claim_token": "tok",
            "assignee": "antigravity",
            "task_class": "coding",
            "objective": "patch",
            "lease_until": "2099-01-01T00:00:00+00:00",
        }
        ev = {
            "commit_sha": "a" * 40,
            "objective_paths": ["x.py"],
            "objective_files_count": 1,
            "test_results": {"exit_code": 0, "ok": True},
            "evidence_source": "git_committed_diff_on_execution_host",
            "gemini_model": "gemini-3.6-flash",
        }
        with patch.object(ior.mongo_store, "get_db") as gdb:
            col = MagicMock()
            gdb.return_value.__getitem__.return_value = col
            col.find_one.return_value = task
            out = ior.complete_ops_task("antigravity", "ops_model_mismatch", claim_token="tok", evidence=ev)
        self.assertFalse(out.get("ok"))
        self.assertEqual(out.get("error"), "model_not_pinned")

    def test_foreign_sha_without_worktree_receipt_rejected(self) -> None:
        ev = {
            "commit_sha": NEBius_SHA,
            "objective_paths": ["platform/docs/marker.md"],
            "objective_files_count": 1,
            "test_results": {"exit_code": 0, "ok": True},
            "host_execution": {"executed": True},
            "postconditions": {"verified": True},
        }
        err = ocp.validate_mutating_completion_evidence({"task_class": "coding", "objective": "fix bug"}, ev)
        self.assertTrue("worktree" in err or "git_baseline" in err, msg=err)

    def test_forged_evidence_source_and_nebius_sha_rejected_without_worktree(self) -> None:
        ev = {
            "evidence_source": "git_committed_diff_on_execution_host",
            "commit_sha": NEBius_SHA,
            "objective_paths": ["platform/inneros_core_runtime/ops_completion_policy.py"],
            "objective_files_count": 1,
            "test_results": {"exit_code": 0, "ok": True},
            "git_before_sha": "a" * 40,
        }
        err = ocp.validate_mutating_completion_evidence(
            {"task_class": "coding", "objective": "patch", "git_baseline_sha": "a" * 40},
            ev,
        )
        self.assertIn("worktree", err)

    def test_forged_evidence_source_rejected_when_commit_not_in_worktree(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name)
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
        baseline = git_head(repo)
        (repo / "marker.md").write_text("exists on disk only\n", encoding="utf-8")
        ev = {
            "evidence_source": "git_committed_diff_on_execution_host",
            "commit_sha": NEBius_SHA,
            "objective_paths": ["marker.md"],
            "objective_files_count": 1,
            "test_results": {"exit_code": 0, "ok": True},
        }
        err = ocp.validate_mutating_completion_evidence(
            {"task_class": "coding", "objective": "patch"},
            ev,
            worktree=repo,
            before_sha=baseline,
        )
        self.assertIsNotNone(err)
        self.assertTrue("receipt" in err or "commit_sha" in err, msg=err)

    def test_repair_task_mentioning_pcdoctor_not_deployment(self) -> None:
        repair = {
            "task_class": "coding",
            "objective": (
                "Fix false COMPLETED gates; regression mentions pcdoctor.ai hosting allowlist "
                "only as context, no production publish"
            ),
        }
        self.assertFalse(ocp.objective_implies_deployment(repair))

    def test_ops_cd287162_p0_gate_task_not_deployment(self) -> None:
        """Repair PR #226 must not require host mutation solely because PCDoctor appears in title."""
        task = {
            "task_class": "coding",
            "title": "P0: fail-closed Antigravity completion gates (ops cd287162b44a)",
            "objective": (
                "Close false COMPLETED for Antigravity headless; stabilize Temporal receipts; "
                "pcdoctor.ai mentioned only as prior false-complete context — no WordPress cpanel publish"
            ),
        }
        self.assertFalse(ocp.objective_implies_deployment(task))

    def test_ops_cd287162_mongo_objective_fragments_not_deployment(self) -> None:
        """Real repair objective mentions deploy/WordPress only as gate requirements, not publish intent."""
        task = {
            "task_class": "coding",
            "title": "P0 CURSOR: reparar falso COMPLETED Antigravity / Temporal",
            "objective": (
                "NO CONFUNDIR CON PUBLICACIÓN DE LAS WEBS. "
                "test_results={} ni deploy sin recibos verificados. "
                "Clasificar hosting/wordpress como deployment. "
                "pcdoctor.ai sigue antigua allowlist sin ambos dominios."
            ),
        }
        self.assertFalse(ocp.objective_implies_deployment(task))

    def test_explicit_wordpress_deploy_still_requires_host_mutation(self) -> None:
        deploy = {"task_class": "coding", "objective": "Deploy landing WordPress to cpanel production site"}
        self.assertTrue(ocp.objective_implies_deployment(deploy))

    def test_negated_cpanel_publish_mention_not_deployment(self) -> None:
        task = {
            "task_class": "coding",
            "objective": "Repair gates; no WordPress cpanel publish during this hotfix",
        }
        self.assertFalse(ocp.objective_implies_deployment(task))

    def test_coordination_live_terminal_validator_fail_closed(self) -> None:
        import importlib.util
        from unittest.mock import patch

        legacy_path = Path(__file__).resolve().parents[1] / "raphiia_openai" / "coordination_live.py"
        spec = importlib.util.spec_from_file_location("legacy_coordination_live", legacy_path)
        assert spec and spec.loader
        cl = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cl)
        task = {"task_id": "ops_terminal_gate", "task_class": "coding", "repo": "org/r"}
        with patch("inneros_core_runtime.ops_completion_policy.validate_terminal_completion", side_effect=RuntimeError("boom")):
            gate = cl._validate_terminal_evidence(task, "completed", {"commit_sha": "a" * 40})
        self.assertFalse(gate.get("ok"))
        self.assertEqual(gate.get("error"), "terminal_evidence_policy_failed")

    def test_untracked_objective_file_fails_without_commit(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name)
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
        baseline = git_head(repo)
        (repo / "platform").mkdir()
        (repo / "platform" / "docs").mkdir()
        phantom = repo / "platform" / "docs" / "ANTIGRAVITY_HEADLESS_64d4bf6d941e.md"
        phantom.write_text("uncommitted phantom receipt\n", encoding="utf-8")
        ev = {
            "commit_sha": baseline,
            "objective_paths": ["platform/docs/ANTIGRAVITY_HEADLESS_64d4bf6d941e.md"],
            "objective_files_count": 1,
            "test_results": {"exit_code": 0, "ok": True},
        }
        task = {"task_class": "coding", "objective": "patch", "git_baseline_sha": baseline}
        err = ocp.validate_mutating_completion_evidence(task, ev, worktree=repo, before_sha=baseline)
        self.assertIsNotNone(err)
        self.assertTrue(
            "receipt" in err or "git_baseline" in err or "commit_sha" in err,
            msg=err,
        )

    def test_canary_real_commit_passes_with_receipt(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name)
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
        baseline = git_head(repo)
        (repo / "platform").mkdir()
        (repo / "platform" / "docs").mkdir()
        marker = repo / "platform" / "docs" / "CURSOR_CANARY.md"
        marker.write_text("canary\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "platform/docs/CURSOR_CANARY.md"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "canary"], check=True)
        head = git_head(repo)
        ev = {
            "commit_sha": head,
            "objective_paths": ["platform/docs/CURSOR_CANARY.md"],
            "objective_files_count": 1,
            "test_results": {"exit_code": 0, "ok": True},
            "evidence_source": "git_committed_diff_on_execution_host",
            "git_before_sha": baseline,
        }
        task = {"task_class": "coding", "objective": "add canary doc only"}
        err = ocp.validate_mutating_completion_evidence(task, ev, worktree=repo, before_sha=baseline)
        self.assertIsNone(err)


if __name__ == "__main__":
    unittest.main()
