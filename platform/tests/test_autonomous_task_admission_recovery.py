"""Tests for Autonomous Task Admission & Execution Recovery (Carril F / ops_tasks).

Covers:
1. Deterministic classification across the 6 task classes: coding, review, research, operations, deployment, monitoring.
2. Filtering of purely informational messages (no spurious coding tasks).
3. Mandatory binding for coding tasks: unbound coding tasks -> waiting_for_binding/BLOCKED instead of empty candidate failure.
4. Specialized completion gates per task_class (non-coding tasks do not require code diffs).
5. Reproduction of failures ops_9811e9e3ba07, ops_73fa730829cf, and ops_46c8b6765a4d.
6. Local-first model routing fallback (AMD -> Intel -> Ollama/deterministic).
7. Canonical successor retry mechanism preserving source_message_id and correlation_id.
"""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from inneros_core_runtime.task_classifier import (
    classify_task_intent,
    is_informational_message,
    validate_coding_bindings,
    TASK_CLASSES,
)
from inneros_core_runtime import (
    coordination_ingest,
    coordination_live,
    local_model_router,
    temporal_bounded_executor,
)
from inneros_core_runtime.temporal_activities import activity_validate_completion_gate


def test_task_classes_completeness():
    assert len(TASK_CLASSES) == 6
    for c in ("coding", "review", "research", "operations", "deployment", "monitoring"):
        assert c in TASK_CLASSES


def test_task_classification_heuristics():
    # 1. Review
    assert classify_task_intent(title="Review PR #122 and verify diff") == "review"
    assert classify_task_intent(title="Revisar cambios de arquitectura en Device Fabric") == "review"

    # 2. Research
    assert classify_task_intent(title="Investigar viabilidad de nuevo protocolo RTSP") == "research"
    assert classify_task_intent(title="Research competitive benchmarks for edge inference") == "research"

    # 3. Operations
    assert classify_task_intent(title="Ejecutar barrido de red en Bellini I-II") == "operations"
    assert classify_task_intent(title="Backup and switch failover dry run") == "operations"

    # 4. Deployment
    assert classify_task_intent(title="Deploy Cloud Run service to production") == "deployment"
    assert classify_task_intent(title="Desplegar worker temporal v2") == "deployment"

    # 5. Monitoring
    assert classify_task_intent(title="Monitoreo de telemetría y métricas de GPU") == "monitoring"
    assert classify_task_intent(title="Telemetry health watchdog sweep") == "monitoring"

    # 6. Coding
    assert classify_task_intent(title="Fix bug in OAuth auth middleware") == "coding"
    assert classify_task_intent(title="Implement new feature for ContributorOps") == "coding"


def test_informational_messages_filter():
    # Status / informational message should NOT create task
    assert is_informational_message(
        message_type="status",
        title="[LANE-B] Bellini Device Fabric Read-Only Unblocked",
        body="Task completed successfully on main.",
    ) is True

    assert is_informational_message(
        message_type="message",
        title="Info update",
        body="All systems nominal.",
    ) is True

    # Explicit task directive should create task
    assert is_informational_message(
        message_type="task",
        title="Fix bug in router",
        body="Repair the route table.",
    ) is False

    assert is_informational_message(
        message_type="message",
        title="[P0] Task for Dev Swarm",
        body="INSTRUCCIÓN P0: reparar el controlador",
    ) is False


def test_coding_task_binding_validation():
    # Missing repo/project
    valid, err = validate_coding_bindings(repo=None, project_id=None, related_project=None)
    assert valid is False
    assert "missing_repo_binding" in err

    # Valid with repo
    valid, err = validate_coding_bindings(repo="Rafa-Innerchispa/innerops-agentic-platform")
    assert valid is True
    assert err is None


def test_reproduction_ops_9811_and_ops_73fa_unbound_coding_task():
    """Reproduce ops_9811e9e3ba07 & ops_73fa730829cf: unbound coding task must not fail empty."""
    envelope = {
        "task_id": "ops_9811e9e3ba07",
        "task_class": "coding",
        "repo": "",  # missing repo binding
        "title": "Unbound coding task",
    }
    candidate = {"response": "plan only", "candidate_only": True}

    res = temporal_bounded_executor.run_bounded_executor(
        envelope_dict=envelope,
        worktree="/tmp/mock_wt",
        candidate=candidate,
    )

    assert res["ok"] is False
    assert res["status"] == "waiting_for_binding"
    assert res["waiting_for_binding"] is True
    assert res["reason"] == "missing_repo_binding"

    # Completion gate should flag waiting_for_binding, not terminal failed without reason
    import asyncio
    gate = asyncio.run(activity_validate_completion_gate(envelope, res))
    assert gate["passed"] is False
    assert gate["status"] == "waiting_for_binding"
    assert gate["blocker"] == "missing_repo_binding"


def test_reproduction_ops_46c8_operations_network_audit_gate():
    """Reproduce ops_46c8b6765a4d: operations task with telemetry passes gate without code diff."""
    envelope = {
        "task_id": "ops_46c8b6765a4d",
        "task_class": "operations",
        "title": "Universal Network Audit read-only sweep",
    }
    agent_result = {
        "ok": True,
        "files_count": 0,
        "code_diff": "",
        "evidence": {
            "mode": "read_only",
            "provider_used": "grandstream_gwn+device_fabric",
            "findings": [{"severity": "info", "code": "audit_complete"}],
        },
        "test_results": {"exit_code": 0, "ok": True},
    }

    import asyncio
    gate = asyncio.run(activity_validate_completion_gate(envelope, agent_result))
    assert gate["passed"] is True
    assert gate["task_class"] == "operations"


def test_review_research_deployment_monitoring_gates():
    import asyncio

    # Review gate
    rev_env = {"task_id": "ops_rev_1", "task_class": "review"}
    rev_res = {"ok": True, "verdict": "APPROVED", "target_sha": "abc1234"}
    assert asyncio.run(activity_validate_completion_gate(rev_env, rev_res))["passed"] is True

    # Research gate
    res_env = {"task_id": "ops_res_1", "task_class": "research"}
    res_res = {"ok": True, "findings": "Found 3 alternative architectures with lower latency."}
    assert asyncio.run(activity_validate_completion_gate(res_env, res_res))["passed"] is True

    # Deployment gate
    dep_env = {"task_id": "ops_dep_1", "task_class": "deployment"}
    dep_res = {"ok": True, "sha": "571f0cd0", "service_health": "SERVING_OK"}
    assert asyncio.run(activity_validate_completion_gate(dep_env, dep_res))["passed"] is True

    # Monitoring gate
    mon_env = {"task_id": "ops_mon_1", "task_class": "monitoring"}
    mon_res = {"ok": True, "metrics": {"gpu_util": 42.5, "temp": 58}}
    assert asyncio.run(activity_validate_completion_gate(mon_env, mon_res))["passed"] is True


def test_local_model_router_fallback():
    # Calling router fallback should succeed and report node / fallback info
    res = local_model_router.run_local_model_with_fallback(
        task_type="operations",
        prompt="Perform health check on node 5",
        primary_node="amd",
        secondary_node="intel",
    )
    assert res.get("ok") is True
    assert "node_used" in res or "fallback_applied" in res


def test_canonical_successor_retry():
    mock_task = {
        "task_id": "ops_orig_123",
        "title": "Task needing retry",
        "retry_count": 0,
        "max_retries": 3,
        "source_message_id": "msg_source_999",
        "correlation_id": "corr_orig_123",
    }

    with patch("inneros_core_runtime.coordination_live.get_ops_task", return_value={"ok": True, "task": mock_task}), \
         patch("inneros_core_runtime.durable_coordination_spine.start_task_workflow", return_value={"ok": True, "run_id": "run_retry_1"}), \
         patch("inneros_core_runtime.coordination_live._publish_task_event", return_value={"ok": True}), \
         patch("inneros_core_runtime.coordination_live.bump_revision", return_value={"ok": True}):

        retry = coordination_live.retry_ops_task("ops_orig_123", reason="Transient network error")

    assert retry["ok"] is True
    assert retry["parent_task_id"] == "ops_orig_123"
    assert retry["retry_count"] == 1
    assert retry["task_id"].startswith("ops_")
