from __future__ import annotations

from unittest import mock

from inneros_core_runtime import dual_deployment


class FakeCollection:
    def __init__(self) -> None:
        self.docs: list[dict] = []

    def find_one(self, query: dict, projection: dict | None = None):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return {key: value for key, value in doc.items() if key != "_id"}
        return None

    def insert_one(self, document: dict):
        self.docs.append(dict(document))
        return mock.Mock(inserted_id="fake")

    def find(self, query: dict, projection: dict | None = None):
        rows = [
            {key: value for key, value in doc.items() if key != "_id"}
            for doc in self.docs
            if all(doc.get(key) == value for key, value in query.items())
        ]
        return FakeCursor(rows)

    def update_one(self, query: dict, update: dict):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                doc.update(update.get("$set", {}))
                return mock.Mock(matched_count=1, modified_count=1)
        return mock.Mock(matched_count=0, modified_count=0)


class FakeCursor:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def sort(self, *_args):
        return self

    def limit(self, count: int):
        return self.rows[:count]


class FakeDb(dict):
    def __getitem__(self, key: str):
        if key not in self:
            self[key] = FakeCollection()
        return dict.__getitem__(self, key)


def test_dual_deployment_contract_is_local_first_and_non_destructive() -> None:
    assert dual_deployment.IDENTITY_CONTRACT["no_blind_db_duplication"] is True
    assert "route local AI tasks to AMD ROCm/vLLM or local worker" in dual_deployment.OFFLINE_MODE["allowed_when_cloud_unreachable"]
    assert "open shell/general execution outside existing Local Execution Plane allowlists" in dual_deployment.OFFLINE_MODE["not_allowed"]


def test_dual_deployment_status_reports_local_and_cloud_without_mutation() -> None:
    with (
        mock.patch.object(dual_deployment, "_systemd_state", return_value={"state": "active", "ok": True}),
        mock.patch.object(dual_deployment, "_http_status", return_value={"status": "up", "http_status": 200}),
        mock.patch.object(dual_deployment, "_gcloud_run_services", return_value={"ok": True, "status": "up", "services": []}),
        mock.patch.object(dual_deployment, "_resource_fabric_snapshot", return_value={"ok": True, "providers": [], "models": []}),
    ):
        status = dual_deployment.dual_deployment_status()

    assert status["ok"] is True
    assert status["overall"] == "up"
    assert status["topology"]["local"]["amd"]["host"] == "192.168.1.5"
    assert status["topology"]["local"]["intel"]["host"] == "192.168.1.4"
    assert any(item["service_id"] == "vllm-rocm10" for item in status["local_services"])
    assert any(item["service_id"] == "inneros-cloud-run" for item in status["cloud_surfaces"])
    assert status["sync_contract"]["current_status"].startswith("contract_ready")


def test_dual_deployment_status_degrades_when_cloud_is_skipped_and_local_down() -> None:
    with (
        mock.patch.object(dual_deployment, "_systemd_state", return_value={"state": "inactive", "ok": False}),
        mock.patch.object(dual_deployment, "_http_status", return_value={"status": "down"}),
        mock.patch.object(dual_deployment, "_resource_fabric_snapshot", return_value={"ok": False}),
    ):
        status = dual_deployment.dual_deployment_status(include_cloud=False)

    assert status["overall"] == "down"
    assert status["cloud_surfaces"] == []
    assert all(item["status"] == "down" for item in status["local_services"])


def test_queue_dual_operation_is_idempotent_and_allowlisted() -> None:
    fake_db = FakeDb()
    with mock.patch.object(dual_deployment, "_db", return_value=fake_db):
        first = dual_deployment.queue_dual_operation(
            source="cloud_ui",
            target="local_amd",
            action="dual_health_probe",
            idempotency_key="k1",
            dry_run=False,
        )
        second = dual_deployment.queue_dual_operation(
            source="cloud_ui",
            target="local_amd",
            action="dual_health_probe",
            idempotency_key="k1",
            dry_run=False,
        )

    assert first["ok"] is True
    assert first["idempotent"] is False
    assert second["ok"] is True
    assert second["idempotent"] is True
    assert dual_deployment.queue_dual_operation(
        source="cloud_ui",
        target="shell",
        action="dual_health_probe",
        idempotency_key="k2",
    )["error"] == "target_not_allowed"


def test_reconcile_dual_operations_marks_queued_items() -> None:
    fake_db = FakeDb()
    with mock.patch.object(dual_deployment, "_db", return_value=fake_db):
        dual_deployment.queue_dual_operation(
            source="local_ui",
            target="local_amd",
            action="dual_health_probe",
            idempotency_key="k3",
            dry_run=False,
        )
        result = dual_deployment.reconcile_dual_operations(dry_run=False)

    assert result["ok"] is True
    assert result["count"] == 1
    assert result["reconciled"][0]["status"] == "reconciled"


def test_dual_deployment_drill_exercises_cloud_local_degraded_reconcile() -> None:
    fake_db = FakeDb()
    with (
        mock.patch.object(dual_deployment, "_db", return_value=fake_db),
        mock.patch.object(dual_deployment, "dual_deployment_status", side_effect=[
            {"overall": "up"},
            {"overall": "up"},
        ]),
    ):
        result = dual_deployment.dual_deployment_drill(dry_run=False)

    assert result["ok"] is True
    assert result["result"] == "PASS"
    assert result["local_degraded_simulation"]["cloud_probe"] == "skipped_by_design"
    assert result["reconcile"]["count"] == 2
