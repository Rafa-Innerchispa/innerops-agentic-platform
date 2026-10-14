from __future__ import annotations

import pytest

from inneros_core_runtime import network_engineer_memory as mem


def test_git_safe_redacts_sensitive_material_and_private_topology():
    raw = {
        "site_id": "bellini-i-ii",
        "password": "plain",
        "credential_ref": "owner_vault:provider/password",
        "ip": "192.168.3.1",
        "mac": "AA:BB:CC:DD:EE:FF",
        "device": {"model": "GCC6010", "serial_number": "ABC123"},
    }
    safe = mem._git_safe(raw)
    assert safe["password"] == "[REDACTED]"
    assert safe["credential_ref"] == "owner_vault:provider/password"
    assert safe["ip"] == "[PRIVATE_TOPOLOGY_IN_ENCRYPTED_DR]"
    assert safe["mac"] == "[PRIVATE_TOPOLOGY_IN_ENCRYPTED_DR]"
    assert safe["device"]["model"] == "GCC6010"
    assert safe["device"]["serial_number"] == "[PRIVATE_TOPOLOGY_IN_ENCRYPTED_DR]"


def test_plaintext_sensitive_value_is_rejected_but_reference_is_allowed():
    with pytest.raises(ValueError, match="plaintext_secret_forbidden"):
        mem._assert_no_secret_material({"credential": "plain-value"})
    mem._assert_no_secret_material({"credential_ref": "owner_vault:provider/key"})


def test_identifier_validation():
    assert mem._clean_site_id("Bellini-I-II") == "bellini-i-ii"
    assert mem._clean_fact_key("topology.core_uplink") == "topology.core_uplink"


def test_git_safe_preserves_recovery_structure():
    raw = {
        "facts": [{"fact_key": "device.role", "value": {"vendor": "Grandstream", "model": "GWN7801P", "role": "distribution_switch"}}],
        "snapshot_index": [{"sha256": "a" * 64, "snapshot_type": "topology"}],
    }
    safe = mem._git_safe(raw)
    assert safe["facts"][0]["value"]["model"] == "GWN7801P"
    assert safe["facts"][0]["value"]["role"] == "distribution_switch"
    assert safe["snapshot_index"][0]["sha256"] == "a" * 64
