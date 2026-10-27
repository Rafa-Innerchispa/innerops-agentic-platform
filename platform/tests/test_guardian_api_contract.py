from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from inneros_core_runtime.guardian_api_routes import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_overview_publishes_minimum_frontend_contract():
    response = _client().get("/api/guardian/overview")
    assert response.status_code == 200
    payload = response.json()
    assert payload["execution_policy"] == "DRY_RUN_PLANNING_ONLY"
    assert len(payload["routes"]) == 5


def test_diagnose_defaults_to_local_and_sanitizes_secret():
    response = _client().post(
        "/api/guardian/diagnose",
        json={
            "telemetry": {
                "device_ref": "ap_01",
                "offline": True,
                "private_ip": "192.168.1.25",
                "api_token": "never-publish-this",
            }
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["inference_mode"] == "LOCAL_HEURISTIC"
    serialized = json.dumps(payload)
    assert "never-publish-this" not in serialized
    assert "192.168.1.25" not in serialized

    evidence = _client().get(f"/api/guardian/evidence/{payload['evidence_id']}")
    assert evidence.status_code == 200


def test_action_plan_forces_dry_run_and_never_accepts_approval_secret():
    response = _client().post(
        "/api/guardian/actions/plan",
        json={
            "capability_id": "network.device.reboot.v1",
            "parameters": {
                "device_ref": "ap_01",
                "dry_run": False,
                "approval_token": "must-not-be-used",
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["result"]["status"] == "STAGED_DRY_RUN"
    assert payload["result"]["result"]["mutation_applied"] is False
    assert "must-not-be-used" not in json.dumps(payload)


def test_recovery_contract_distinguishes_simulation_from_real_probe_gap():
    simulated = _client().post(
        "/api/guardian/recovery/verify",
        json={"device_ref": "ap_01", "provider": "unifi", "simulation": True},
    ).json()
    assert simulated["result"]["result"]["verification_mode"] == "SIMULATED"

    unavailable = _client().post(
        "/api/guardian/recovery/verify",
        json={"device_ref": "ap_01", "provider": "unifi", "simulation": False},
    ).json()
    assert unavailable["ok"] is False
    assert unavailable["result"]["result"]["error"] == "provider_probe_unavailable"
