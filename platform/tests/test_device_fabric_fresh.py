from inneros_core_runtime import device_fabric
from inneros_core_runtime.agents import agent_catalog, pool_agent_runners
from inneros_core_runtime.mcp_catalog import tool_catalog
from inneros_core_runtime import mcp_profiles


EXPECTED_PROVIDERS = {
    "generic_network",
    "generic_onvif",
    "generic_rtsp",
    "upnp_ssdp_mdns",
    "home_assistant_registry",
    "hikvision",
    "dahua",
    "tp_link_tapo",
    "imou",
    "ezviz",
    "zkteco",
    "grandstream_ucm",
    "grandstream_gwn",
    "intelbras",
    "unifi",
    "dmx",
    "broadlink",
    "tuya",
    "alexa_devices",
}

EXPECTED_TOOLS = [
    "device_fabric_providers",
    "device_fabric_discover",
    "device_fabric_probe",
    "device_fabric_bind",
    "device_fabric_inventory",
    "device_fabric_capabilities",
    "device_fabric_health",
    "device_fabric_get",
]


def test_provider_registry_is_complete_and_truthful():
    rows = device_fabric.device_fabric_providers()
    assert rows["ok"] is True
    assert rows["agent_id"] == "AG-60"
    assert {row["provider_id"] for row in rows["providers"]} == EXPECTED_PROVIDERS
    states = {row["support_state"] for row in rows["providers"]}
    assert states <= {
        "ready",
        "partial",
        "auth_required",
        "unsupported",
        "transport_unavailable",
        "not_validated",
    }


def test_small_mcp_surface_and_profile_are_registered():
    for name in EXPECTED_TOOLS:
        assert name in tool_catalog.ALL_MCP_TOOL_NAMES
        assert name in tool_catalog.TOOL_DEFINITIONS
    profile = mcp_profiles.get_profile("device_fabric")
    assert profile["ok"] is True
    assert profile["tool_count"] == 8
    assert profile["tools"] == EXPECTED_TOOLS
    assert mcp_profiles.validate_profiles()["ok"] is True


def test_schema_contains_required_fields_and_redacts_secret_reference():
    record = device_fabric.canonical_device_record(
        site_id="bellini_i_ii",
        tenant_id="pcdoctor",
        name="test-camera",
        ip="192.168.3.144",
        mac="AA:BB:CC:00:11:22",
        manufacturer="Hikvision",
        provider_ids=["hikvision"],
        protocols=["rtsp"],
        credential_ref_present=True,
    )
    for field in (
        "device_id",
        "tenant_id",
        "site_id",
        "name",
        "ip",
        "host",
        "mac",
        "manufacturer",
        "model",
        "firmware",
        "serial",
        "device_type",
        "protocols",
        "provider_ids",
        "capabilities",
        "credential_ref_present",
        "transport",
        "evidence",
        "provenance",
        "confidence",
        "last_seen",
        "health",
        "control_route",
        "mutation_policy",
    ):
        assert field in record
    assert "credential_ref" not in record

    bind = device_fabric.device_fabric_bind(
        "192.168.3.144",
        "hikvision",
        credential_ref="owner_vault://bellini/hikvision-secret",
        dry_run=True,
    )
    assert bind["ok"] is True
    assert bind["credential_ref_present"] is True
    assert bind["would_register"]["credential_ref"] == "[REDACTED]"
    assert "hikvision-secret" not in str(bind)


def test_live_bind_is_fail_closed_and_bellini_scope_is_isolated():
    live_bind = device_fabric.device_fabric_bind("192.168.3.144", "hikvision", dry_run=False)
    assert live_bind["ok"] is False
    assert live_bind["error"] == "live_bind_disabled_in_read_only_task"
    assert live_bind["mutations_attempted"] == []

    outside = device_fabric.device_fabric_probe("192.168.1.4", site_id="bellini_i_ii")
    assert outside["ok"] is False
    assert outside["error"] == "target_outside_authorized_site_cidr"

    wrong_cidr = device_fabric.device_fabric_discover(site_id="bellini_i_ii", cidr="192.168.1.0/24", live=False)
    assert wrong_cidr["ok"] is False
    assert wrong_cidr["error"] == "cidr_not_authorized_for_site"


def test_vendor_fingerprints_cover_requested_classes():
    hik = device_fabric._fingerprint(
        "192.168.3.144",
        [80, 554],
        {"rtsp": {"headers": "RTSP/1.0 401 Unauthorized\r\nWWW-Authenticate: Basic realm=\"DS-K1T344\""}},
    )
    assert "hikvision" in hik["provider_ids"]
    assert hik["device_type"] == "camera_or_video_intercom"
    assert "video_intercom_candidate" in hik["capabilities"]

    dahua = device_fabric._fingerprint("192.168.3.14", [80, 554, 37777], {})
    assert "dahua" in dahua["provider_ids"]
    assert "generic_rtsp" in dahua["provider_ids"]
    assert "analog_child_channels_possible" in dahua["capabilities"]

    ucm = device_fabric._fingerprint("192.168.0.50", [5060, 8088], {"banner": "Asterisk Grandstream UCM6104"})
    assert "grandstream_ucm" in ucm["provider_ids"]

    gwn = device_fabric._fingerprint("192.168.0.51", [80, 443], {"banner": "Grandstream GWN controller GCC"})
    assert "grandstream_gwn" in gwn["provider_ids"]

    web_only = device_fabric._fingerprint("192.168.3.14", [80, 443, 554, 8088], {})
    assert "grandstream_ucm" not in web_only["provider_ids"]


def test_closed_port_protocol_names_do_not_create_vendor_false_positives():
    raw = {
        "tcp": [
            {"port": 80, "protocol": "http", "state": "open"},
            {"port": 554, "protocol": "rtsp", "state": "closed"},
            {"port": 8000, "protocol": "hikvision_sdk", "state": "closed"},
            {"port": 37777, "protocol": "dahua_private", "state": "closed"},
            {"port": 5060, "protocol": "sip", "state": "closed"},
        ],
        "http_80": {"ok": True, "headers": "Server: generic", "body_sample": ""},
    }
    generic = device_fabric._fingerprint("192.168.3.50", [80], raw)
    assert generic["provider_ids"] == ["generic_network"]
    assert generic["manufacturer"] == "unknown"


def test_delegations_and_home_assistant_correlation_helpers():
    provider_rows = {row["provider_id"]: row for row in device_fabric.device_fabric_providers()["providers"]}
    assert "innerspark-workforce-ai" in provider_rows["zkteco"]["delegated_to"]
    assert "AG-59" in provider_rows["dmx"]["delegated_to"]
    assert "Home Assistant" in provider_rows["unifi"]["delegated_to"]
    assert "UniFi Controller" in provider_rows["unifi"]["delegated_to"]
    assert "inneros-physical-guardian" in provider_rows["intelbras"]["delegated_to"]

    ids = device_fabric._ha_provider_ids(
        {"name": "Alexa Tuya Broadlink room"},
        [{"entity_id": "switch.tuya_plug"}, {"entity_id": "remote.broadlink_rm"}],
    )
    assert {"home_assistant_registry", "alexa_devices", "tuya", "broadlink"} <= set(ids)


def test_dedupe_merges_providers_protocols_and_evidence():
    first = device_fabric.canonical_device_record(
        site_id="home_pcdoctor_lab",
        tenant_id="innerchispa",
        ip="192.168.0.10",
        provider_ids=["unifi"],
        protocols=["http"],
        capabilities=["inventory"],
        evidence=[{"source": "a"}],
        confidence=0.4,
    )
    second = device_fabric.canonical_device_record(
        site_id="home_pcdoctor_lab",
        tenant_id="innerchispa",
        ip="192.168.0.10",
        provider_ids=["intelbras"],
        protocols=["https"],
        capabilities=["alarm"],
        evidence=[{"source": "b"}],
        confidence=0.8,
    )
    merged = device_fabric.dedupe_devices([first, second])
    assert len(merged) == 1
    assert merged[0]["provider_ids"] == ["intelbras", "unifi"]
    assert merged[0]["protocols"] == ["http", "https"]
    assert merged[0]["capabilities"] == ["alarm", "inventory"]
    assert len(merged[0]["evidence"]) == 2
    assert merged[0]["confidence"] == 0.8


def test_ag60_is_registered_and_invokable_locally():
    entry = agent_catalog.get_catalog_entry("AG-60")
    assert entry is not None
    assert entry["mcp_profile"] == "device_fabric"
    assert entry["entry_tool"] == "invoke_agent"
    runners = pool_agent_runners.get_runner_registry()
    assert "AG-60" in runners
    result = runners["AG-60"]("provider matrix", dry_run=True)
    assert result["ok"] is True
    assert result["agent_id"] == "AG-60"
    assert result["provider_count"] == len(EXPECTED_PROVIDERS)
