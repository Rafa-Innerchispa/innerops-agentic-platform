import pytest
from unittest.mock import patch, MagicMock
from inneros_core_runtime import vultr_cloud_provider


def test_redact_secrets():
    payload = {
        "vultr_api_key": "4FAKEXXX1234567890ABCDEF1234",
        "nested": {"token": "SECRET12345", "safe": "value"},
        "safe_list": ["regular", "item"],
    }
    redacted = vultr_cloud_provider._redact(payload)
    assert redacted["vultr_api_key"] == "[REDACTED]"
    assert redacted["nested"]["token"] == "[REDACTED]"
    assert redacted["nested"]["safe"] == "value"


def test_resource_provider_document():
    doc = vultr_cloud_provider.resource_provider_document()
    assert doc["provider_id"] == "vultr-cloud"
    assert doc["kind"] == "cloud_infrastructure"
    assert "cloud_vm" in doc["capabilities"]
    assert doc["status"] == "active"
    assert doc["local_first"] is False


def test_plan_instance_dry_run():
    plan = vultr_cloud_provider.plan_instance(
        region="mia",
        plan="vc2-1c-1gb",
        label="test-vm",
    )
    assert plan["ok"] is True
    assert plan["dry_run"] is True
    assert plan["proposed_configuration"]["region"] == "mia"
    assert plan["proposed_configuration"]["plan"] == "vc2-1c-1gb"
    assert "monthly_usd" in plan["estimated_pricing"]
    assert plan["governance"]["spend_approval_required"] is True


def test_create_instance_dry_run_default():
    res = vultr_cloud_provider.create_instance(
        region="mia",
        plan="vc2-1c-1gb",
        os_id=2105,
        label="safe-vm",
        dry_run=True,
    )
    assert res["ok"] is True
    assert res["dry_run"] is True
    assert res["status"] == "dry_run_approved"


def test_create_instance_fails_closed_without_owner_approval():
    res = vultr_cloud_provider.create_instance(
        region="mia",
        plan="vc2-1c-1gb",
        os_id=2105,
        label="unauthorized-vm",
        dry_run=False,
        owner_approved=False,
    )
    assert res["ok"] is False
    assert res["error"] == "owner_approval_required"
    assert res["dry_run"] is True


def test_destroy_instance_dry_run_default():
    res = vultr_cloud_provider.destroy_instance(
        instance_id="inst-12345",
        dry_run=True,
    )
    assert res["ok"] is True
    assert res["dry_run"] is True
    assert res["status"] == "dry_run_only"


def test_destroy_instance_fails_closed_without_owner_approval():
    res = vultr_cloud_provider.destroy_instance(
        instance_id="inst-12345",
        dry_run=False,
        owner_approved=False,
    )
    assert res["ok"] is False
    assert res["error"] == "owner_approval_required"
    assert res["dry_run"] is True


@patch("inneros_core_runtime.vultr_cloud_provider._request")
def test_account_mocked(mock_request):
    mock_request.return_value = {
        "account": {
            "balance": -250.0,
            "pending_charges": 1.25,
        }
    }
    acct = vultr_cloud_provider.account()
    assert acct["ok"] is True
    assert acct["balance"] == -250.0
    assert acct["credit_available_usd"] == 250.0
    assert acct["pending_charges"] == 1.25


@patch("inneros_core_runtime.vultr_cloud_provider._request")
def test_list_instances_mocked(mock_request):
    mock_request.return_value = {
        "instances": [
            {
                "id": "vultr-uuid-1",
                "label": "inneros-vultr-vm",
                "status": "active",
                "power_status": "running",
                "main_ip": "45.77.164.161",
                "region": "mia",
                "plan": "vc2-1c-2gb",
                "vcpu_count": 1,
                "ram": 2048,
                "disk": 55,
            }
        ]
    }
    res = vultr_cloud_provider.list_instances()
    assert res["ok"] is True
    assert res["count"] == 1
    assert res["instances"][0]["id"] == "vultr-uuid-1"
    assert res["instances"][0]["main_ip"] == "45.77.164.161"
