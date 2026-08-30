from __future__ import annotations

from unittest import mock

from inneros_core_runtime import dual_deployment


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
