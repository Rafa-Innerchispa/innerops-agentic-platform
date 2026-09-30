import pytest
from inneros_core_runtime import bellini_network_guardian as bng


def test_target_definitions_are_complete():
    targets = bng.TARGETS
    ips = [t["ip"] for t in targets]
    assert "192.168.3.1" in ips
    assert "192.168.3.2" in ips
    assert "192.168.3.100" in ips
    assert "192.168.3.185" in ips
    assert "192.168.3.188" in ips
    assert "192.168.3.212" in ips
    assert "192.168.3.213" in ips
    assert "192.168.3.216" in ips
    assert "192.168.3.227" in ips


def test_mutation_policy_strictly_read_only():
    assert bng.MUTATION_POLICY["mode"] == "read_only"
    assert "live_ap_reboot_without_owner_approval" in bng.MUTATION_POLICY["forbidden"]
    assert "live_vlan_change" in bng.MUTATION_POLICY["forbidden"]


def test_governed_action_dry_run_vs_live():
    # Dry run should succeed and return plan
    dry = bng.reboot_ap("bellini_ap_188", dry_run=True)
    assert dry.get("ok") is True
    assert dry.get("status") == "STAGED_DRY_RUN"
    assert dry.get("mutation_applied") is False

    # Live execution without token should fail closed
    live = bng.reboot_ap("bellini_ap_188", dry_run=False)
    assert live.get("ok") is False
    assert live.get("error") == "governed_action_requires_explicit_owner_approval"
    assert live.get("mutation_applied") is False


def test_governed_radio_and_power_actions():
    radio = bng.toggle_radio("bellini_ap_188", radio="5ghz", enabled=False, dry_run=True)
    assert radio.get("ok") is True
    assert radio.get("plan", {}).get("params", {}).get("radio") == "5ghz"

    channel = bng.change_channel("bellini_ap_188", radio="2.4ghz", channel=11, dry_run=True)
    assert channel.get("ok") is True
    assert channel.get("plan", {}).get("params", {}).get("channel") == 11


def test_capture_sweep_and_status():
    status = bng.bellini_guardian_status()
    assert status.get("ok") is True
    assert "gateway_online" in status or "source" in status


def test_dashboard_format():
    dash = bng.bellini_guardian_dashboard()
    assert dash.get("ok") is True
    assert dash.get("site_id") == "bellini-i-ii"
    assert dash.get("client_id") == "bellini"
    assert "gateway" in dash
    assert "device_matrix" in dash
    assert dash.get("mutation_policy", {}).get("mode") == "read_only"
