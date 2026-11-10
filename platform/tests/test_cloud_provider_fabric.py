import pytest
from unittest.mock import patch
from inneros_core_runtime import cloud_provider_fabric


def test_list_providers_includes_all_four():
    res = cloud_provider_fabric.list_providers()
    assert res["ok"] is True
    assert res["count"] == 4
    pids = {p["provider_id"] for p in res["providers"]}
    assert "vultr-cloud" in pids
    assert "digitalocean-amd-cloud" in pids
    assert "nebius-nvidia" in pids
    assert "local-amd-5" in pids


def test_get_credits_status_truthful():
    res = cloud_provider_fabric.get_credits_status()
    assert res["ok"] is True
    credits = {c["provider"]: c for c in res["credits"]}
    assert "vultr-cloud" in credits
    assert "digitalocean-amd-cloud" in credits
    assert "nebius-nvidia" in credits
    assert "local-amd-5" in credits
    # Truthfulness checks
    assert credits["nebius-nvidia"]["balance_usd"] == "UNKNOWN"
    assert credits["nebius-nvidia"]["verified"] is False
    assert credits["local-amd-5"]["verified"] is True


def test_plan_instance_vultr():
    plan = cloud_provider_fabric.plan_instance("vultr-cloud", region="mia", plan="vc2-1c-1gb", label="test-vm")
    assert plan["ok"] is True
    assert plan["dry_run"] is True
    assert "monthly_usd" in plan["estimated_pricing"]


def test_plan_instance_digitalocean():
    plan = cloud_provider_fabric.plan_instance("digitalocean-amd-cloud", region="nyc1", plan="s-1vcpu-1gb", label="test-droplet")
    assert plan["ok"] is True
    assert plan["dry_run"] is True


def test_create_instance_unauthorized_rejection():
    res = cloud_provider_fabric.create_instance(
        provider_id="vultr-cloud",
        region="mia",
        plan="vc2-1c-1gb",
        label="unauthorized-vm",
        dry_run=False,
        owner_approved=False,
    )
    assert res["ok"] is False
    assert res["error"] == "owner_approval_required"


def test_compare_pricing_recommends_local():
    res = cloud_provider_fabric.compare_pricing({"vcpu": 1, "ram_gb": 1})
    assert res["ok"] is True
    assert "local-amd-5" in res["best_cost_option"]
    assert len(res["comparison"]) == 3
