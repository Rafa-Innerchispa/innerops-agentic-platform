from __future__ import annotations

import sys
from pathlib import Path

PLATFORM = Path(__file__).resolve().parents[1]
PLATFORM_TEXT = str(PLATFORM)
sys.path[:] = [item for item in sys.path if item != PLATFORM_TEXT]
sys.path.insert(0, PLATFORM_TEXT)

for prefix in ("raphiia_openai", "inneros_core_runtime"):
    for module_name in [name for name in sys.modules if name == prefix or name.startswith(prefix + ".")]:
        sys.modules.pop(module_name, None)

from inneros_core_runtime.agents import ag55_browser_ops_agent as ag55


def test_ag55_import_is_from_current_worktree():
    assert Path(ag55.__file__).resolve().is_relative_to(PLATFORM)


def test_alpaca_domain_is_explicitly_allowlisted():
    result = ag55._url_allowed_result("https://app.alpaca.markets/")
    assert result["ok"] is True
    assert result["mode"] == "domain_allowlist"


def test_private_lan_target_is_blocked():
    result = ag55._url_allowed_result("http://192.168.1.50:8080/")
    assert result["ok"] is False
    assert result["error"] == "private_or_metadata_host_blocked"


def test_metadata_target_is_blocked():
    result = ag55._url_allowed_result("http://169.254.169.254/latest/meta-data")
    assert result["ok"] is False
    assert result["error"] == "private_or_metadata_host_blocked"


def test_loopback_requires_explicit_port():
    blocked = ag55._url_allowed_result("http://127.0.0.1:8111/status")
    allowed = ag55._url_allowed_result("http://127.0.0.1:8111/status", local_preview=True, loopback_ports=[8111])
    assert blocked["ok"] is False
    assert blocked["error"] == "loopback_not_allowlisted"
    assert allowed["ok"] is True
    assert allowed["port"] == 8111
