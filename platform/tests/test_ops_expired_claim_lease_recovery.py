from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import pytest

from inneros_core_runtime import ops_interactive_recovery as oir
from inneros_core_runtime import ops_awaiting_claim as oac


def test_expired_interactive_claim_is_recovered():
    """1. Lease vencido + worker terminado -> recuperacion controlada."""
    past_lease = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    task = {
        "task_id": "ops_stale_claim_probe",
        "status": "claimed",
        "assignee": "inneros_orchestrator",
        "preferred_provider": "antigravity",
        "execution_lane": "antigravity_interactive",
        "claim_token": "token_stale_12345",
        "lease_until": past_lease,
        "claimed_at": past_lease,
        "claimed_by": "antigravity",
        "revision": 3,
    }

    mock_db = MagicMock()
    mock_col = MagicMock()
    mock_db.__getitem__.return_value = mock_col

    mock_col.find.return_value.sort.return_value.limit.return_value = [task]
    update_result = MagicMock()
    update_result.modified_count = 1
    mock_col.update_one.return_value = update_result

    with patch.object(oir.mongo_store, "get_db", return_value=mock_db):
        res = oir.recover_orphan_interactive_ops_tasks(limit=10)

    # Must find and recover the expired claim
    assert res["ok"] is True
    assert len(res["recovered"]) == 1
    assert res["recovered"][0]["task_id"] == "ops_stale_claim_probe"
    assert res["recovered"][0]["status"] == "awaiting_antigravity_claim"

    # Verify atomic multi-field CAS verified status, token, lease_until, and revision
    mock_col.update_one.assert_called_once()
    filter_arg, update_arg = mock_col.update_one.call_args[0]
    assert filter_arg["task_id"] == "ops_stale_claim_probe"
    assert filter_arg["status"] == "claimed"
    assert filter_arg["claim_token"] == "token_stale_12345"
    assert filter_arg["lease_until"] == past_lease
    assert filter_arg["revision"] == 3
    assert update_arg["$set"]["status"] == "awaiting_antigravity_claim"
    assert "claim_token" in update_arg["$unset"]
    assert "lease_until" in update_arg["$unset"]
    assert "claimed_at" in update_arg["$unset"]


def test_active_valid_lease_is_never_recovered():
    """Lease activo y valido (< now) -> no recuperar."""
    future_lease = (datetime.now(timezone.utc) + timedelta(minutes=45)).isoformat()
    task = {
        "task_id": "ops_active_live_worker",
        "status": "claimed",
        "assignee": "inneros_orchestrator",
        "preferred_provider": "cursor",
        "execution_lane": "cursor_interactive",
        "claim_token": "valid_token_live",
        "lease_until": future_lease,
        "claimed_at": (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat(),
        "claimed_by": "cursor",
    }

    mock_db = MagicMock()
    mock_col = MagicMock()
    mock_db.__getitem__.return_value = mock_col

    mock_col.find.return_value.sort.return_value.limit.return_value = [task]

    with patch.object(oir.mongo_store, "get_db", return_value=mock_db):
        res = oir.recover_orphan_interactive_ops_tasks(limit=10)

    assert res["ok"] is True
    assert len(res["recovered"]) == 0
    mock_col.update_one.assert_not_called()


def test_expired_lease_with_active_worker_pid_is_never_recovered():
    """2. Lease vencido + worker PID activo -> CERO WRITES (no recuperar)."""
    past_lease = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    task = {
        "task_id": "ops_running_worker_expired_lease",
        "status": "claimed",
        "assignee": "inneros_orchestrator",
        "preferred_provider": "antigravity",
        "execution_lane": "antigravity_interactive",
        "claim_token": "token_active_proc",
        "lease_until": past_lease,
        "claimed_by": "antigravity",
        "headless_execution_pid": 99999,
    }

    mock_db = MagicMock()
    mock_col = MagicMock()
    mock_db.__getitem__.return_value = mock_col
    mock_col.find.return_value.sort.return_value.limit.return_value = [task]

    # Mock os.kill(pid, 0) succeeding -> Process is alive!
    with patch("os.kill", return_value=None):
        with patch.object(oir.mongo_store, "get_db", return_value=mock_db):
            res = oir.recover_orphan_interactive_ops_tasks(limit=10)

    assert res["ok"] is True
    assert len(res["recovered"]) == 0
    # GUARANTEE: ZERO WRITES
    mock_col.update_one.assert_not_called()


def test_expired_lease_with_recent_heartbeat_is_never_recovered():
    """2b. Lease vencido + heartbeat reciente (< 3 min) -> CERO WRITES."""
    past_lease = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    recent_heartbeat = (datetime.now(timezone.utc) - timedelta(seconds=45)).isoformat()
    task = {
        "task_id": "ops_heartbeating_expired_lease",
        "status": "claimed",
        "assignee": "inneros_orchestrator",
        "preferred_provider": "cursor",
        "execution_lane": "cursor_interactive",
        "claim_token": "token_heartbeating",
        "lease_until": past_lease,
        "claimed_by": "cursor",
        "heartbeat_at": recent_heartbeat,
    }

    mock_db = MagicMock()
    mock_col = MagicMock()
    mock_db.__getitem__.return_value = mock_col
    mock_col.find.return_value.sort.return_value.limit.return_value = [task]

    with patch.object(oir.mongo_store, "get_db", return_value=mock_db):
        res = oir.recover_orphan_interactive_ops_tasks(limit=10)

    assert res["ok"] is True
    assert len(res["recovered"]) == 0
    # GUARANTEE: ZERO WRITES
    mock_col.update_one.assert_not_called()


def test_concurrent_renewal_cas_failure_declares_zero_recovered():
    """3. Lease renovado concurrentemente -> CAS falla (modified_count == 0) -> no sobrescribir ni contar."""
    past_lease = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    task = {
        "task_id": "ops_renewed_concurrently",
        "status": "claimed",
        "assignee": "inneros_orchestrator",
        "preferred_provider": "codex",
        "execution_lane": "codex_interactive",
        "claim_token": "token_concurrent",
        "lease_until": past_lease,
        "claimed_by": "codex",
        "revision": 5,
    }

    mock_db = MagicMock()
    mock_col = MagicMock()
    mock_db.__getitem__.return_value = mock_col
    mock_col.find.return_value.sort.return_value.limit.return_value = [task]

    # Simulate another worker renewing the lease concurrent with this query: modified_count == 0
    update_result = MagicMock()
    update_result.modified_count = 0
    mock_col.update_one.return_value = update_result

    with patch.object(oir.mongo_store, "get_db", return_value=mock_db):
        res = oir.recover_orphan_interactive_ops_tasks(limit=10)

    assert res["ok"] is True
    # Must NOT count as recovered because CAS update did not match
    assert len(res["recovered"]) == 0


def test_racing_recovery_two_processes_only_one_gets_claim():
    """4. Dos procesos intentando recuperar -> solo uno puede obtener el claim (modified_count == 1)."""
    past_lease = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    task = {
        "task_id": "ops_racing_target",
        "status": "claimed",
        "assignee": "inneros_orchestrator",
        "preferred_provider": "antigravity",
        "execution_lane": "antigravity_interactive",
        "claim_token": "token_race",
        "lease_until": past_lease,
        "claimed_by": "antigravity",
        "revision": 2,
    }

    mock_db = MagicMock()
    mock_col = MagicMock()
    mock_db.__getitem__.return_value = mock_col
    mock_col.find.return_value.sort.return_value.limit.return_value = [task]

    # Process 1 succeeds
    p1_res = MagicMock(modified_count=1)
    mock_col.update_one.return_value = p1_res
    with patch.object(oir.mongo_store, "get_db", return_value=mock_db):
        res1 = oir.recover_orphan_interactive_ops_tasks(limit=10)
    assert len(res1["recovered"]) == 1

    # Process 2 arrives with stale snapshot -> CAS modified_count == 0
    p2_res = MagicMock(modified_count=0)
    mock_col.update_one.return_value = p2_res
    with patch.object(oir.mongo_store, "get_db", return_value=mock_db):
        res2 = oir.recover_orphan_interactive_ops_tasks(limit=10)
    assert len(res2["recovered"]) == 0


def test_awaiting_claim_precedence_for_orchestrated_tasks():
    """Provider awaiting resolution for orchestrated tasks."""
    t_anti = {
        "task_id": "ops_orch_1",
        "assignee": "inneros_orchestrator",
        "preferred_provider": "antigravity",
    }
    assert oac.awaiting_claim_status_for_task(t_anti) == "awaiting_antigravity_claim"

    t_cur = {
        "task_id": "ops_orch_2",
        "assignee": "inneros_orchestrator",
        "claimed_by": "cursor",
    }
    assert oac.awaiting_claim_status_for_task(t_cur) == "awaiting_cursor_claim"

    t_codex = {
        "task_id": "ops_orch_3",
        "assignee": "dev_swarm",
        "execution_lane": "codex_interactive",
    }
    assert oac.awaiting_claim_status_for_task(t_codex) == "awaiting_codex_claim"

    t_direct = {
        "task_id": "ops_orch_4",
        "assignee": "antigravity",
    }
    assert oac.awaiting_claim_status_for_task(t_direct) == "awaiting_antigravity_claim"


def test_expired_lease_on_remote_host_unverified_is_never_recovered():
    """5. Lease vencido en host remoto (Intel 1.4) sin verificacion de ausencia -> CERO WRITES."""
    past_lease = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    task = {
        "task_id": "ops_remote_intel_worker",
        "status": "claimed",
        "assignee": "inneros_orchestrator",
        "preferred_provider": "antigravity",
        "execution_lane": "antigravity_interactive",
        "claim_token": "token_remote_intel",
        "claim_host": "ralphi-ia-ver-10",
        "lease_until": past_lease,
        "claimed_by": "antigravity",
        "headless_execution_pid": 42424,
        "revision": 4,
    }

    mock_db = MagicMock()
    mock_col = MagicMock()
    mock_db.__getitem__.return_value = mock_col
    mock_col.find.return_value.sort.return_value.limit.return_value = [task]

    with patch("socket.gethostname", return_value="ralfiia-amd"):
        with patch.object(oir.mongo_store, "get_db", return_value=mock_db):
            res = oir.recover_orphan_interactive_ops_tasks(limit=10)

    assert res["ok"] is True
    assert len(res["recovered"]) == 0
    assert len(res["skipped_active"]) == 1
    assert "remote_host_unverified:ralphi-ia-ver-10" in res["skipped_active"][0]["reason"]
    mock_col.update_one.assert_not_called()


def test_expired_lease_on_remote_host_with_verified_absence_is_recovered():
    """5b. Lease vencido en host remoto con verificador explicito de ausencia (False) -> recupera con CAS."""
    past_lease = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    task = {
        "task_id": "ops_remote_intel_verified_dead",
        "status": "claimed",
        "assignee": "inneros_orchestrator",
        "preferred_provider": "antigravity",
        "execution_lane": "antigravity_interactive",
        "claim_token": "token_remote_dead",
        "claim_host": "ralphi-ia-ver-10",
        "lease_until": past_lease,
        "claimed_by": "antigravity",
        "headless_execution_pid": 42424,
        "revision": 4,
    }

    mock_db = MagicMock()
    mock_col = MagicMock()
    mock_db.__getitem__.return_value = mock_col
    mock_col.find.return_value.sort.return_value.limit.return_value = [task]
    mock_col.update_one.return_value = MagicMock(modified_count=1)

    with patch("socket.gethostname", return_value="ralfiia-amd"):
        with patch.object(oir.mongo_store, "get_db", return_value=mock_db):
            res = oir.recover_orphan_interactive_ops_tasks(
                limit=10,
                remote_liveness_verifier=lambda host, pid: False,
            )

    assert res["ok"] is True
    assert len(res["recovered"]) == 1
    assert res["recovered"][0]["task_id"] == "ops_remote_intel_verified_dead"
    mock_col.update_one.assert_called_once()


def test_expired_lease_with_linked_worktree_gitdir_file_lock_is_never_recovered(tmp_path):
    """6. Worktree con archivo .git ('gitdir: ...') y lock activo en gitdir real -> CERO WRITES."""
    real_gitdir = tmp_path / "repo_root" / ".git" / "worktrees" / "wt_repair"
    real_gitdir.mkdir(parents=True)
    (real_gitdir / "index.lock").write_text("locked", encoding="utf-8")

    wt_dir = tmp_path / "worktrees" / "wt_repair"
    wt_dir.mkdir(parents=True)
    (wt_dir / ".git").write_text(f"gitdir: {real_gitdir}\n", encoding="utf-8")

    past_lease = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    task = {
        "task_id": "ops_gitdir_file_locked",
        "status": "claimed",
        "assignee": "inneros_orchestrator",
        "preferred_provider": "antigravity",
        "execution_lane": "antigravity_interactive",
        "claim_token": "token_wt_locked",
        "lease_until": past_lease,
        "claimed_by": "antigravity",
        "worktree": str(wt_dir),
        "revision": 2,
    }

    mock_db = MagicMock()
    mock_col = MagicMock()
    mock_db.__getitem__.return_value = mock_col
    mock_col.find.return_value.sort.return_value.limit.return_value = [task]

    with patch.object(oir.mongo_store, "get_db", return_value=mock_db):
        res = oir.recover_orphan_interactive_ops_tasks(limit=10)

    assert res["ok"] is True
    assert len(res["recovered"]) == 0
    assert len(res["skipped_active"]) == 1
    assert res["skipped_active"][0]["reason"] == "worktree_git_locked"
    mock_col.update_one.assert_not_called()

