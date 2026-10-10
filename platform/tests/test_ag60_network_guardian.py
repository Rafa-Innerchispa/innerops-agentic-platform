"""AG-60 bounded scanner safety and evidence contract."""
from unittest import mock
import pytest
import importlib.util
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "inneros_core_runtime" / "network_guardian.py"
SPEC = importlib.util.spec_from_file_location("candidate_ag60_network_guardian", PATH)
network_guardian = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(network_guardian)


def test_unknown_site_rejected():
    with pytest.raises(ValueError):
        network_guardian.authorized_network("unregistered_site")


def test_outside_cidr_rejected_before_probe():
    with pytest.raises(ValueError, match="outside"):
        network_guardian.probe_host("8.8.8.8", "home_pcdoctor_lab")


def test_failed_ping_is_not_offline():
    with mock.patch.object(network_guardian, "icmp_probe", return_value={"status": "NO_REPLY"}), mock.patch.object(
        network_guardian, "tcp_probe", return_value=[]
    ):
        result = network_guardian.probe_host("192.168.1.20", "home_pcdoctor_lab")
    assert result["health"] == "UNKNOWN"
    assert result["reachable"] is None


def test_tcp_reachable_without_icmp():
    with mock.patch.object(network_guardian, "icmp_probe", return_value={"status": "NO_REPLY"}), mock.patch.object(
        network_guardian, "tcp_probe", return_value=[443]
    ):
        result = network_guardian.probe_host("192.168.1.20", "home_pcdoctor_lab")
    assert result["health"] == "ONLINE"
    assert result["tcp_open"] == [443]


def test_scan_limits():
    with pytest.raises(ValueError):
        network_guardian.scan_site(limit_hosts=999)
    with pytest.raises(ValueError):
        network_guardian.scan_site(workers=100)


def test_correlation_not_claim_root_cause():
    events = [{"ip": str(i), "previous_state": "ONLINE", "new_state": "UNKNOWN"} for i in range(3)]
    result = network_guardian.correlate_events(events)
    assert result[0]["cause"] == "UNDETERMINED"
