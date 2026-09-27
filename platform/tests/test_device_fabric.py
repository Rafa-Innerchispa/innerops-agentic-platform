from __future__ import annotations

from unittest import mock

from inneros_core_runtime import device_fabric
from inneros_core_runtime.agents import agent_catalog, pool_agent_runners


def test_provider_matrix_contains_required_integrations() -> None:
    out = device_fabric.device_fabric_providers()
    provider_ids = {row["provider_id"] for row in out["providers"]}

    assert out["ok"] is True
    assert {
        "hikvision",
        "dahua",
        "tplink_tapo",
        "imou",
        "ezviz",
        "zkteco_adms_iclock",
        "grandstream_ucm",
        "grandstream_gwn",
        "intelbras",
        "unifi_ubiquiti",
        "dmx_ag59",
        "broadlink",
        "tuya",
        "alexa",
        "onvif",
        "rtsp",
        "generic_network",
    }.issubset(provider_ids)

    zkteco = next(row for row in out["providers"] if row["provider_id"] == "zkteco_adms_iclock")
    assert "innerspark-workforce-ai" in zkteco["reused_from"]
    dmx = next(row for row in out["providers"] if row["provider_id"] == "dmx_ag59")
    assert "AG-59 DMX" in dmx["reused_from"]


def test_bellini_scope_is_fail_closed() -> None:
    wrong_cidr = device_fabric.device_fabric_discover("bellini_i_ii", cidr="192.168.1.0/24", live=False)
    assert wrong_cidr["ok"] is False
    assert wrong_cidr["error"] == "cidr_not_authorized_for_site"

    outside = device_fabric.device_fabric_probe("192.168.1.4", site_id="bellini_i_ii")
    assert outside["ok"] is False
    assert outside["error"] == "target_outside_authorized_site_cidr"


def test_classification_handles_video_and_voice_fingerprints() -> None:
    hik = device_fabric._classify(
        "192.168.3.144",
        [80, 443, 554],
        {"rtsp_554": {"response_preview": 'RTSP/1.0 401 Unauthorized\r\nWWW-Authenticate: Digest realm="DS-K1T344"'}},
    )
    assert "hikvision" in hik["provider_ids"]
    assert hik["device_type"] == "camera_or_video_intercom"

    dahua = device_fabric._classify("192.168.3.50", [80, 554, 37777], {})
    assert "dahua" in dahua["provider_ids"]
    assert dahua["device_type"] == "camera_or_dvr_nvr"

    grandstream = device_fabric._classify("192.168.3.2", [80, 5060, 8088], {"http": {"body": "Asterisk"}})
    assert "grandstream_ucm" in grandstream["provider_ids"]
    assert grandstream["device_type"] == "pbx_or_voice_gateway"


def test_bind_is_dry_run_only_and_redacts_credentials() -> None:
    preview = device_fabric.device_fabric_bind(
        "bellini_i_ii:hikvision:192.168.3.144",
        "hikvision",
        credential_ref="owner-vault://secret/hikvision-admin",
        dry_run=True,
    )
    assert preview["ok"] is True
    assert preview["dry_run"] is True
    assert preview["would_register"]["credential_ref"] == "[REDACTED]"

    live = device_fabric.device_fabric_bind("device", "hikvision", dry_run=False)
    assert live["ok"] is False
    assert live["error"] == "live_bind_disabled_in_read_only_fabric"
    assert live["mutations_attempted"] == []


def test_home_provider_detection_uses_existing_home_assistant_surface() -> None:
    device = {
        "id": "broadlink-1",
        "name": "RM Mini Living",
        "manufacturer": "Broadlink",
        "model": "RM Mini 3",
    }
    entities = [{"device_id": "broadlink-1", "platform": "broadlink", "entity_id": "remote.rm_mini"}]
    assert device_fabric._providers_for_ha_device(device, entities) == ["broadlink"]

    unifi = {"id": "ap1", "name": "U7", "manufacturer": "Ubiquiti Networks", "model": "U7HD"}
    assert device_fabric._providers_for_ha_device(unifi, []) == ["unifi_ubiquiti"]


def test_agent_catalog_and_runner_register_ag60() -> None:
    meta = agent_catalog.get_catalog_entry("AG-60")
    assert meta is not None
    assert meta["mcp_profile"] == "device_fabric"
    assert "hikvision" in meta["intent_keywords"]

    runners = pool_agent_runners.get_runner_registry()
    assert "AG-60" in runners
    with mock.patch.object(device_fabric, "device_fabric_health", return_value={"ok": True, "provider_count": 17}):
        out = runners["AG-60"](message="", dry_run=True)
    assert out["ok"] is True
    assert out["agent_id"] == "AG-60"
    assert out["provider_count"] == 17
