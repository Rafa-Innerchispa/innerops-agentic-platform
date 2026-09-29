import ast
from pathlib import Path
import pytest
from inneros_core_runtime.agents import ag55_browser_ops_agent as ag55


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "inneros_core_runtime"
    / "agents"
    / "ag55_browser_ops_agent.py"
)


def _default_allowlist():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == "DEFAULT_ALLOWLIST"
                for target in node.targets
            ):
                return tuple(ast.literal_eval(node.value))
    raise AssertionError("DEFAULT_ALLOWLIST assignment not found")


def test_amazon_and_gwn_domains_are_explicitly_allowlisted():
    allowlist = _default_allowlist()
    assert "developer.amazon.com" in allowlist
    assert "amazon.com" in allowlist
    assert "gwn.cloud" in allowlist
    assert "grandstream.com" in allowlist


def test_browser_allowlist_does_not_add_wildcard_hosts():
    allowlist = _default_allowlist()
    assert all("*" not in host for host in allowlist)
    assert "developer.amazon.com" in allowlist
    assert "amazon.com" in allowlist


def test_bellini_subnet_is_specifically_allowed():
    # 192.168.3.0/24 endpoints are allowed
    assert ag55._host_allowed("http://192.168.3.1") is True
    assert ag55._host_allowed("https://192.168.3.1:8443") is True
    assert ag55._host_allowed("http://192.168.3.188") is True
    assert ag55._host_allowed("http://192.168.3.212") is True
    assert ag55._host_allowed("http://192.168.3.216") is True
    assert ag55._host_allowed("http://192.168.3.227") is True

    guard_res = ag55._url_allowed_result("https://192.168.3.1:8443")
    assert guard_res.get("ok") is True
    assert guard_res.get("scope") == "bellini_read_only"


def test_other_private_subnets_are_strictly_forbidden():
    # Other private networks must be rejected
    assert ag55._host_allowed("http://192.168.1.1") is False
    assert ag55._host_allowed("http://10.0.0.1") is False
    assert ag55._host_allowed("http://172.16.0.1") is False
    assert ag55._host_allowed("http://192.168.0.1") is False

    guard_fail = ag55._url_allowed_result("http://192.168.1.1")
    assert guard_fail.get("ok") is False
    assert guard_fail.get("error") == "private_network_forbidden"


def test_external_unallowlisted_domains_are_forbidden():
    assert ag55._host_allowed("http://malicious-site.com") is False
    guard = ag55._url_allowed_result("http://unauthorized.org/page")
    assert guard.get("ok") is False
    assert guard.get("error") == "domain_not_allowlisted"
