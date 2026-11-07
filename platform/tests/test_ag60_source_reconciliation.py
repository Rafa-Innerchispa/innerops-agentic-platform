"""AG-60 cloud-versus-Guardian reconciliation with offline vendor-like fixtures."""
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "inneros_core_runtime"))
from ag60_source_reconciliation import reconcile


NOW = datetime(2026, 10, 19, 22, 30, tzinfo=timezone.utc)


def guardian(*targets):
    return {"timestamp": NOW.isoformat(), "targets": list(targets)}


def cloud(*rows):
    return {"ok": True, "devices": {"all": {"items": [
        {"status": 1, "lastSeen": int(NOW.timestamp() * 1000), **row} for row in rows]}}}


def test_ip_only_cannot_establish_same_device():
    g = guardian({"asset_id": "old", "name": "AP 212", "ip": "192.168.3.212", "online": False})
    snap = cloud({"apType": "GWN7660", "mac": "EC:74:D7:3D:27:2C",
                  "ipv4": "192.168.3.212", "name": "Salón Inglés"})
    r = reconcile(g, {"inventory": []}, snap, now=NOW)
    assert r["comparisons"][0]["identity_match"] == "IP_ONLY_UNVERIFIED"
    assert r["comparisons"][0]["classification"] == "POTENTIAL_IDENTITY_MATCH_VERIFY_MAC"
    assert not r["root_cause_verified"]


def test_mac_match_with_different_ip_is_not_a_confirmed_outage():
    g = guardian({"asset_id": "gateway", "name": "Gateway", "ip": "192.168.3.1", "online": True})
    inv = {"inventory": [{"asset_id": "gateway", "mac": "ec:74:d7:23:bc:91"}]}
    snap = cloud({"apType": "GCC6010", "mac": "EC:74:D7:23:BC:91",
                  "ipv4": "192.168.1.1", "name": "Router Principal"})
    result = reconcile(g, inv, snap, now=NOW)["comparisons"][0]
    assert result["identity_match"] == "INVENTORY_MAC"
    assert result["classification"] == "IP_DIFFERENCE_VERIFY_INTERFACES_OR_DHCP"
    assert result["root_cause_verified"] is False


def test_cloud_aps_missing_from_guardian_are_counted():
    g = guardian({"asset_id": "only", "ip": "192.168.3.212", "online": True})
    snap = cloud({"apType": "GWN7605", "mac": "EC:74:D7:1A:01:D0",
                  "ipv4": "192.168.3.197", "name": "Lobby Principal"},
                 {"apType": "GWN7801P", "mac": "EC:74:D7:13:EE:B8",
                  "ipv4": "192.168.3.226", "name": "Switch Consola"})
    r = reconcile(g, {"inventory": []}, snap, now=NOW)
    assert r["cloud_devices"] == 2
    assert r["unmonitored_cloud_aps"] == 1
    assert r["cloud_accesspoints_not_monitored"][0]["name"] == "Lobby Principal"


def test_stale_sources_dont_certify_current_connectivity():
    g = {"timestamp": "2026-10-18T20:00:00+00:00",
         "targets": [{"asset_id": "ap", "ip": "192.168.3.212", "online": False}]}
    snap = cloud({"apType": "GWN7660", "mac": "EC:74:D7:3D:27:2C",
                  "ipv4": "192.168.3.212", "name": "Salón Inglés"})
    r = reconcile(g, {"inventory": []}, snap, now=NOW)
    assert r["status"] == "GUARDIAN_STALE"
    assert r["comparisons"][0]["classification"] == "GUARDIAN_SAMPLE_STALE"


def test_no_cloud_read_is_unavailable_not_zero_devices():
    r = reconcile(guardian(), {"inventory": []}, {"ok": False}, now=NOW)
    assert r["status"] == "UNAVAILABLE"
    assert not r["identity_verified_by_ip_only"]


def test_fresh_mac_match_conflicting_online_is_not_physical_cause():
    snap = cloud({"apType": "GWN7660", "mac": "EC:74:D7:3D:27:2C",
                  "ipv4": "192.168.3.212", "name": "Salón Inglés"})
    g = guardian({"asset_id": "ap212", "ip": "192.168.3.212", "online": False})
    inv = {"inventory": [{"asset_id": "ap212", "mac": "ec74d73d272c"}]}
    r = reconcile(g, inv, snap, now=NOW)
    assert r["comparisons"][0]["classification"] == "DIFFERENT_SOURCE_CONNECTIVITY_EVIDENCE"
    assert r["comparisons"][0]["root_cause_verified"] is False


def test_incomplete_cloud_snapshot_is_unavailable():
    current = guardian()
    for response in [
        {"ok": True, "devices": {"all": {"ok": False, "items": []}}},
        {"ok": True, "devices": {"all": {"ok": False, "items": [
            {"name": "stale", "apType": "GWN7660", "ipv4": "192.168.3.212"}]}}},
        {"ok": True, "devices": {"all": {}}},
        {"ok": True, "devices": {"all": {"items": []}}},
    ]:
        result = reconcile(current, {"inventory": []}, response, now=NOW)
        assert result["status"] == "UNAVAILABLE"
        assert result["identity_verified_by_ip_only"] is False


def test_stale_cloud_unmatched_device_not_reported_as_new_unmonitored_ap():
    now_ms = int((NOW.timestamp() - 7200) * 1000)
    snap = {"ok": True, "devices": {"all": {"ok": True, "items": [
        {"apType": "GWN7660", "mac": "EC:74:D7:3D:27:2C",
         "ipv4": "192.168.3.212", "name": "Salón Inglés",
         "status": 1, "lastSeen": now_ms}]}}}
    result = reconcile(guardian(), {"inventory": []}, snap, now=NOW)
    assert result["status"] == "CLOUD_STALE"
    assert result["cloud_stale_devices"] == 1
    assert result["comparisons"][0]["classification"] == "CLOUD_SAMPLE_STALE"
    assert result["unmonitored_cloud_aps"] == 0


def test_switch_and_router_models_never_count_as_unmonitored_aps():
    snap = cloud(
        {"apType": "GWN7802P", "mac": "EC:74:D7:13:EE:B9",
         "ipv4": "192.168.3.228", "name": "Switch Torre"},
        {"apType": "GWN7052F", "mac": "EC:74:D7:13:EE:C0",
         "ipv4": "192.168.3.207", "name": "Router WiFi"},
        {"apType": "GWN7660", "mac": "EC:74:D7:3D:27:2C",
         "ipv4": "192.168.3.212", "name": "Salón Inglés"},
    )
    result = reconcile(guardian(), {"inventory": []}, snap, now=NOW)
    assert result["unmonitored_cloud_aps"] == 1
    assert result["cloud_accesspoints_not_monitored"][0]["name"] == "Salón Inglés"


def test_provider_ap_family_overrides_untrusted_model_guess():
    snap = cloud(
        {"apType": "OTHER", "mac": "EC:74:D7:3D:27:2C",
         "ipv4": "192.168.3.212", "name": "AP con modelo pendiente"},
        {"apType": "GWN7802P", "mac": "EC:74:D7:13:EE:B9",
         "ipv4": "192.168.3.228", "name": "Switch"},
    )
    snap["devices"]["access_points"] = {"items": [
        {"mac": "EC:74:D7:3D:27:2C", "apType": "OTHER"}]}
    result = reconcile(guardian(), {"inventory": []}, snap, now=NOW)
    assert result["unmonitored_cloud_aps"] == 1
    assert result["cloud_accesspoints_not_monitored"][0]["name"] == "AP con modelo pendiente"


def test_partial_stale_cloud_snapshot_not_certified_current():
    snap = cloud(
        {"apType": "GWN7660", "mac": "EC:74:D7:3D:27:2C",
         "ipv4": "192.168.3.212", "name": "Salón Inglés"},
        {"apType": "GWN7605", "mac": "EC:74:D7:1A:01:D0",
         "ipv4": "192.168.3.197", "name": "Lobby Principal"},
    )
    snap["devices"]["all"]["items"][1]["lastSeen"] = int((NOW.timestamp() - 7200) * 1000)
    result = reconcile(guardian(), {"inventory": []}, snap, now=NOW)
    assert result["status"] == "PARTIAL_CLOUD_STALE"
    assert result["cloud_stale_devices"] == 1
    assert result["unmonitored_cloud_aps"] == 1
