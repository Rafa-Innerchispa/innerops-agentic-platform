import ast
from pathlib import Path


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
