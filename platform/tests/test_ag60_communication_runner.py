"""AG-60 periodic coordinator tests: independent sources survive HA failure."""
import importlib.util
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "ag60_runner_candidate",
    Path(__file__).resolve().parents[1] / "inneros_core_runtime" / "communication_runner.py",
)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_empty_ha_does_not_stop_critical_hosts_or_usb():
    fake_probe = lambda ip, site: {"ip": ip, "health": "UNKNOWN"}
    with patch.object(runner, "live_home_snapshot", side_effect=RuntimeError("HA down")), patch.object(
        runner, "probe_host", side_effect=fake_probe
    ), patch.object(runner, "host_observation", return_value={"usb": [], "host": "amd"}), patch.object(
        runner, "read_unifi_site", return_value={"ok": False, "error": "unifi_key_missing"}
    ):
        result = runner.collect_cycle(critical_hosts={"gateway": "192.168.1.1"})
    assert result["ok"] is True
    assert result["partial"] is True
    assert result["observation"]["critical_hosts"][0]["label"] == "gateway"
    assert result["observation"]["collector_host"]["host"] == "amd"
    assert "ha_observer:RuntimeError" in result["observation"]["gaps"]


def test_storage_not_invoked_without_save():
    with patch.object(runner, "live_home_snapshot", return_value={
        "ok": True, "devices": [], "unifi_controller": {"ok": True},
        "collector_host": {}, "gaps": []
    }), patch.object(runner, "write_history") as store:
        result = runner.collect_cycle(critical_hosts={})
    assert result["saved"] is False
    store.assert_not_called()


def test_unknown_sites_cannot_be_scanned():
    result = runner.collect_cycle(site_id="somebody_else", critical_hosts={})
    assert result["ok"] is False
