"""Resource admission tests use an in-memory Mongo implementation, never live services."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading

import mongomock
import pytest

from inneros_core_runtime import execution_resource_guard as guard


@pytest.fixture
def db(monkeypatch):
    database = mongomock.MongoClient().isolated_resource_guard_tests
    monkeypatch.setattr(guard.mongo_store, "get_db", lambda: database)
    database[guard.TASKS].insert_one({
        "task_id": "ops_test", "status": "in_progress", "assignee": "cursor",
        "owner_authorized_at": "2026-10-29T00:00:00Z", "claim_token": "test",
    })
    return database


def task(db):
    return db[guard.TASKS].find_one({"task_id": "ops_test"})


@pytest.mark.parametrize("provider", ["cursor", "codex", "antigravity", "dev_swarm", "temporal"])
@pytest.mark.parametrize("change", [
    {"status": "verification"}, {"status": "completed"}, {"status": "cancelled"},
    {"status": "failed"}, {"superseded_by": "ops_new"},
    {"execution_stop": {"actor": "rafael"}}, {"do_not_auto_dispatch": True},
    {"payload": {"do_not_auto_dispatch": True}}, {"execution_paused_for_deploy": True},
    {"execution_lane": "cursor_interactive"},
])
def test_all_providers_obey_lifecycle_and_stop(db, provider, change):
    db[guard.TASKS].update_one({"task_id": "ops_test"}, {"$set": change})
    assert not guard.reserve("ops_test", provider)["ok"]
    assert not task(db).get("resource_guard", {}).get("attempts")


def test_restart_and_provider_change_cannot_reset_attempt_budget(db):
    for provider in ["cursor", "codex", "dev_swarm"]:
        r = guard.reserve("ops_test", provider)
        assert r["ok"]
        guard.finish(r, elapsed=1, success=False)
    assert not guard.reserve("ops_test", "temporal")["ok"]
    assert task(db)["resource_guard"]["attempts"] == 3


def test_success_cannot_repeat_while_projection_waits_for_verification(db):
    r = guard.reserve("ops_test", "cursor")
    guard.finish(r, elapsed=1, success=True)
    assert not guard.reserve("ops_test", "cursor")["ok"]


def test_only_one_parallel_executor_can_reserve_task(db):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: guard.reserve("ops_test", "cursor"), range(8)))
    assert sum(r["ok"] for r in results) == 1
    assert task(db)["resource_guard"]["attempts"] == 1


def test_wall_time_budget_survives_a_new_process(db):
    db[guard.TASKS].update_one({"task_id": "ops_test"}, {"$set": {"resource_guard.elapsed_seconds": 1800}})
    assert not guard.reserve("ops_test", "cursor")["ok"]


def test_nested_calls_share_budget_and_bound_model_requests(db):
    @guard.guard_local_inference
    def model():
        return {"ok": True}

    @guard.guard_execution("dev_swarm", "worker")
    def inner(worker):
        return [model() for _ in range(13)]

    @guard.guard_execution("temporal", "worker")
    def outer(worker):
        results = inner(worker)
        assert all(r["ok"] for r in results[:12])
        assert not results[-1]["ok"]
        return {"ok": True}

    assert outer({"task_id": "ops_test"})["ok"]
    assert task(db)["resource_guard"]["attempts"] == 1
    assert task(db)["resource_guard"]["model_calls"] == 12


def test_gpu_concurrency_has_four_shared_leases(db):
    ready = threading.Barrier(5)
    release = threading.Event()

    @guard.guard_local_inference
    def model():
        ready.wait(timeout=10)
        release.wait(timeout=10)
        return {"ok": True}

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(model) for _ in range(4)]
        try:
            ready.wait(timeout=10)
            assert model()["error"] == "resource_local_inference_capacity_full"
        finally:
            release.set()
        assert all(f.result()["ok"] for f in futures)
    assert db[guard.STATE].count_documents({"state.token": {"$exists": True}}) == 0


def test_execution_exception_releases_mutex_but_does_not_refund_attempt(db):
    @guard.guard_execution("cursor", "tid")
    def work(tid):
        raise RuntimeError("test")
    with pytest.raises(RuntimeError):
        work("ops_test")
    assert task(db)["resource_guard"]["attempts"] == 1
    assert "active_token" not in task(db)["resource_guard"]


def test_async_temporal_activity_preserves_annotations_and_budget(db):
    @guard.guard_execution("temporal", "envelope")
    async def work(envelope: dict) -> dict:
        return {"ok": True}
    assert asyncio.run(work({"task_id": "ops_test"}))["ok"]
    assert work.__annotations__["envelope"] is dict
    assert not asyncio.run(work({"task_id": "ops_test"}))["ok"]


def test_ledger_outage_blocks_before_invoking_executor(monkeypatch):
    monkeypatch.setattr(guard.mongo_store, "get_db", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    @guard.guard_execution("cursor", "tid")
    def work(tid):
        pytest.fail("must not call paid executor")
    assert work("ops_test")["error"] == "resource_ledger_unavailable"


def test_deployed_entrypoints_reject_cancelled_task_before_io(db):
    from inneros_core_runtime import cursor_headless_executor, interactive_provider_bounded_executor
    from inneros_core_runtime import dev_swarm_scheduler, temporal_activities
    db[guard.TASKS].update_one({"task_id": "ops_test"}, {"$set": {"status": "cancelled"}})
    assert not cursor_headless_executor.execute_claimed_task({"task_id": "ops_test"})["ok"]
    assert not interactive_provider_bounded_executor.execute_claimed_task("ops_test", "codex")["ok"]
    assert not dev_swarm_scheduler._execute_existing_worker_generic({"task_id": "ops_test"})["ok"]
    assert not asyncio.run(temporal_activities._execute_budgeted_internal_graph({"task_id": "ops_test"}, {}))["ok"]


def test_provider_daily_allowance_is_atomic_across_different_tasks(db):
    from inneros_core_runtime.external_repair_agent import DEFAULT_DAILY_HARD_LIMIT
    for n in range(DEFAULT_DAILY_HARD_LIMIT["cursor"] + 1):
        tid = f"ops_daily_{n}"
        db[guard.TASKS].insert_one({"task_id": tid, "status": "in_progress", "assignee": "cursor",
                                    "owner_authorized_at": "test", "claim_token": "test"})
        result = guard.reserve(tid, "cursor")
        assert result["ok"] is (n < DEFAULT_DAILY_HARD_LIMIT["cursor"])


def test_pytest_cannot_leak_a_task_into_live_temporal(monkeypatch):
    from inneros_core_runtime import durable_coordination_spine as spine
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_fixture")
    monkeypatch.setattr(spine, "_run_async", lambda *a: pytest.fail("must not reach Temporal"))
    assert spine.start_task_workflow({"task_id": "fixture"})["error"] == "live_task_admission_forbidden_during_pytest"


def test_unbound_development_task_is_rejected_before_workflow(monkeypatch):
    from inneros_core_runtime import coordination_live
    result = coordination_live.create_ops_task(assignee="codex", title="unbound fixture",
                                               task_class="coding", execution_lane="local_dev_swarm")
    assert result["error"] == "blocked_missing_task_binding"


def test_global_circuit_blocks_external_and_local_work(db):
    db[guard.STATE].insert_one({"key": guard.CONTROL_KEY, "state": {"block_new_work": True}})
    assert guard.reserve("ops_test", "cursor")["error"] == "resource_global_circuit_open"
    @guard.guard_local_inference
    def model():
        pytest.fail("must not invoke inference")
    assert model()["error"] == "resource_global_circuit_open"
