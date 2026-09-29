import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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


def test_amazon_developer_domains_are_explicitly_allowlisted():
    allowlist = _default_allowlist()
    assert "developer.amazon.com" in allowlist
    assert "amazon.com" in allowlist


def test_browser_allowlist_does_not_add_wildcard_hosts():
    allowlist = _default_allowlist()
    assert all("*" not in host for host in allowlist)
    assert "developer.amazon.com" in allowlist
    assert "amazon.com" in allowlist



def test_human_browser_url_guard_allows_amazon_developer():
    result = ag55._url_allowed_result("https://developer.amazon.com/alexa/console/ask")
    assert result["ok"] is True
    assert result["reason"] == "domain_allowlist"


def test_human_browser_url_guard_denies_unlisted_external_host():
    result = ag55._url_allowed_result("https://evil.example/")
    assert result["ok"] is False
    assert result["reason"] == "domain_not_allowlisted"


def test_human_browser_url_guard_loopback_requires_explicit_preview_port():
    denied = ag55._url_allowed_result("http://127.0.0.1:8765/demo")
    assert denied["ok"] is False
    assert denied["reason"] == "loopback_preview_disabled"

    wrong_port = ag55._url_allowed_result(
        "http://127.0.0.1:8765/demo",
        local_preview=True,
        loopback_ports=[8766],
    )
    assert wrong_port["ok"] is False
    assert wrong_port["reason"] == "loopback_port_not_allowlisted"

    allowed = ag55._url_allowed_result(
        "http://127.0.0.1:8765/demo",
        local_preview=True,
        loopback_ports=[8765],
    )
    assert allowed["ok"] is True
    assert allowed["reason"] == "loopback_port_allowlist"
