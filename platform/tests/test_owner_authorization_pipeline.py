"""Owner grant must persist independently from agent availability, never forge a claim."""
from unittest.mock import MagicMock, patch

from inneros_core_runtime import cursor_ops_orchestrator as orchestrator
from inneros_core_runtime import cursor_ops_runner as cursor
from inneros_core_runtime import codex_ops_runner as codex
from inneros_core_runtime import interactive_ops_runner as generic


def test_owner_order_offline_persists_approval_and_does_not_claim():
    with (
        patch.object(orchestrator.cor, "authorize_ops_task_for_cursor", return_value={"ok": True, "task_id": "ops_a"}) as auth,
        patch.object(orchestrator.cor, "claim_ops_task") as claim,
        patch.object(orchestrator.cep, "classify_cursor_execution", return_value={"execution_classification": "remote_inbox_only"}),
        patch.object(orchestrator.cep, "read_session_liveness", return_value={"active": False}),
    ):
        out = orchestrator.owner_order_execute(task_id="ops_a", owner_approved=True)
    assert out["stage"] == "authorized_waiting_for_executor"
    auth.assert_called_once()
    claim.assert_not_called()


def test_owner_order_denied_never_authorizes():
    with patch.object(orchestrator.cor, "authorize_ops_task_for_cursor") as auth:
        out = orchestrator.owner_order_execute(task_id="ops_a", owner_approved=False)
    assert not out["ok"]
    auth.assert_not_called()


def test_failed_durable_authorization_does_not_claim():
    with (
        patch.object(orchestrator.cor, "authorize_ops_task_for_cursor", return_value={"ok": False, "error": "task_not_found"}),
        patch.object(orchestrator.cor, "claim_ops_task") as claim,
    ):
        out = orchestrator.owner_order_execute(task_id="ops_missing", owner_approved=True)
    assert out["stage"] == "authorization"
    claim.assert_not_called()


def test_provider_grants_are_filtered_to_unclaimed_assigned_tasks():
    for module, function, kwargs, expected in [
        (cursor, cursor.authorize_ops_task_for_cursor, {}, "cursor"),
        (codex, codex.authorize_ops_task_for_codex, {}, "codex"),
        (generic, generic.authorize_ops_task, {"provider": "antigravity"}, "antigravity"),
    ]:
        collection = MagicMock()
        collection.find_one_and_update.return_value = None
        db = MagicMock()
        db.__getitem__.return_value = collection
        with patch.object(module.mongo_store, "get_db", return_value=db):
            if kwargs:
                result = function(task_id="ops_wrong", **kwargs)
            else:
                result = function("ops_wrong")
        assert not result["ok"]
        query = collection.find_one_and_update.call_args.args[0]
        assert query["assignee"] == expected
        assert query["claim_token"] == {"$exists": False}
        assert "completed" in query["status"]["$nin"]
