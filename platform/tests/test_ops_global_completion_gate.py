"""COMPLETED_VERIFIED gate: no terminal close when agent or evidence denies global completion."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from inneros_core_runtime import ops_global_completion_gate as ogcg
from inneros_core_runtime import ops_lifecycle as ol
from inneros_core_runtime import racb_protocol as racb
from inneros_core_runtime.execution_receipts import git_head


def _git_repo_with_commit() -> tuple[tempfile.TemporaryDirectory, Path, str, str]:
    tmp = tempfile.TemporaryDirectory()
    repo = Path(tmp.name)
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
    base = git_head(repo)
    (repo / "src").mkdir()
    (repo / "src" / "x.py").write_text("x=1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "src/x.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "feat"], check=True)
    head = git_head(repo)
    return tmp, repo, base, head


def test_agent_report_no_completed_global_blocks_gate():
    task = {"task_id": "ops_false_close", "task_class": "coding", "repo": "org/r"}
    evidence = {
        "report": "Estado: NO COMPLETED global hasta CI verde y deploy autorizado.",
        "summary": "work in progress",
    }
    out = ogcg.evaluate_global_completion(task, evidence)
    assert out["ok"] is False
    assert "agent_report_denies_global_completion" in out["reasons"]


def test_read_only_verification_can_pass_global_gate():
    task = {
        "task_id": "ops_revparse",
        "task_class": "verification",
        "objective": "git rev-parse HEAD on worktree",
        "evidence_required": ["commit_sha"],
    }
    evidence = {"commit_sha": "a" * 40, "summary": "sha ok"}
    out = ogcg.evaluate_global_completion(task, evidence)
    assert out["ok"] is True
    assert out["certification"] == "COMPLETED_VERIFIED"
    assert out["receipt"]["task_id"] == "ops_revparse"


def test_coding_task_requires_real_commit_receipt():
    tmp, repo, base, head = _git_repo_with_commit()
    try:
        task = {
            "task_id": "ops_coding",
            "task_class": "coding",
            "repo": "org/r",
            "worktree": str(repo),
            "git_baseline_sha": base,
        }
        evidence = {
            "commit_sha": head,
            "objective_paths": ["src/x.py"],
            "objective_files_count": 1,
            "test_results": {"exit_code": 0, "ok": True},
            "git_before_sha": base,
            "worktree": str(repo),
            "evidence_source": "git_committed_diff_on_execution_host",
        }
        out = ogcg.evaluate_global_completion(task, evidence)
        assert out["ok"] is True
        assert out["receipt"]["commit_sha"] == head
    finally:
        tmp.cleanup()


def test_racb_completed_rejects_pass_without_verified_receipt():
    ev = {"status": "PASS", "result": "PASS", "commit_sha": "e" * 40}
    out = racb.validate_evidence("completed", ev)
    assert out["ok"] is False
    assert out["error"] == "completed_verified_receipt_required"


def test_finalize_verification_rejects_agent_denial_cas():
    db = MagicMock()
    tasks = MagicMock()
    db.__getitem__.return_value = tasks
    task = {
        "task_id": "ops_6e3e49716e6c",
        "status": "verification",
        "revision": 2,
        "task_class": "implementation",
        "repo": "org/r",
        "candidate_evidence": {
            "notes": "**NO COMPLETED** hasta merge PR y audit Intel.",
        },
    }
    tasks.find_one.side_effect = [task, task]
    with patch("raphiia_openai.mongo_store.get_db", return_value=db):
        out = ol.finalize_verification_to_completed("ops_6e3e49716e6c", evidence={"status": "PASS"})
    assert out["ok"] is False
    assert out["error"] == "global_completion_gate_failed"
    tasks.update_one.assert_not_called()


def test_synthetic_canary_never_verifies():
    task = {"task_id": "ops_canary", "task_class": "verification", "objective": "rev-parse"}
    evidence = {"commit_sha": "b" * 40, "canary_class": "SYNTHETIC_CANARY_PASS"}
    out = ogcg.evaluate_global_completion(task, evidence)
    assert out["ok"] is False
    assert "synthetic_canary_not_real_provider" in out["reasons"]


def test_raphiia_mcp_complete_ops_task_is_fail_closed():
    from raphiia_openai import coordination_live as raph_cl

    out = raph_cl.complete_ops_task("ops_mcp_bypass", evidence={"commit_sha": "c" * 40})
    assert out["ok"] is False
    assert out["error"] == "direct_completion_forbidden"
    assert out["authority"] == "temporal"


def test_raphiia_mcp_direct_completed_transition_denied():
    from raphiia_openai import coordination_live as raph_cl

    db = MagicMock()
    tasks = MagicMock()
    db.__getitem__.return_value = tasks
    tasks.find_one.return_value = {"task_id": "ops_x", "status": "verification", "revision": 1}
    with patch("raphiia_openai.mongo_store.get_db", return_value=db):
        out = raph_cl.update_ops_task_state("ops_x", "completed", actor="codex", evidence={"status": "PASS"})
    assert out["ok"] is False
    assert out["error"] == "temporal_owns_task_lifecycle"
    tasks.update_one.assert_not_called()


def test_finalize_verification_cas_race_does_not_terminal_close():
    """Concurrent amend/revision bump must not mark completed when CAS update_one misses."""
    db = MagicMock()
    tasks = MagicMock()
    db.__getitem__.return_value = tasks
    task = {
        "task_id": "ops_race",
        "status": "verification",
        "revision": 4,
        "task_class": "verification",
        "objective": "git rev-parse HEAD on worktree",
        "evidence_required": ["commit_sha"],
    }
    tasks.find_one.side_effect = [task, task]
    change = MagicMock()
    change.modified_count = 0
    tasks.update_one.return_value = change
    gate_ok = {
        "ok": True,
        "certification": "COMPLETED_VERIFIED",
        "receipt": {"task_id": "ops_race", "certification": "COMPLETED_VERIFIED"},
        "temporal_gate": {"passed": True},
    }
    with patch("raphiia_openai.mongo_store.get_db", return_value=db):
        with patch("inneros_core_runtime.ops_global_completion_gate.evaluate_global_completion", return_value=gate_ok):
            with patch("inneros_core_runtime.ops_lifecycle.emit_owner_terminal_whatsapp") as wa:
                out = ol.finalize_verification_to_completed(
                    "ops_race",
                    evidence={"commit_sha": "d" * 40, "summary": "ok"},
                )
    assert out["ok"] is False
    assert out["error"] == "concurrent_completion_race"
    wa.assert_not_called()
