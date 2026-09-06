from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_profile_install_script_defaults_to_inneros_core_and_compact_profile() -> None:
    source = (ROOT / "scripts" / "install_mcp_profile_service.sh").read_text(encoding="utf-8")

    assert 'ROOT="${RALFIA_ROOT:-/home/rlopez/inneros/inneros_core/platform}"' in source
    assert 'PROFILE="${1:-chatgpt_compact}"' in source
    assert 'PORT="${2:-8112}"' in source
    assert "/home/rlopez/projects/raphiia-openai" not in source
    assert "from inneros_core_runtime.mcp_profiles import get_profile" in source
    assert "PYTHONPATH=%s" in source


def test_profile_systemd_unit_uses_canonical_runtime() -> None:
    source = (ROOT / "deploy" / "systemd" / "ralfia-mcp-profile@.service").read_text(encoding="utf-8")

    assert "WorkingDirectory=/home/rlopez/inneros/inneros_core/platform" in source
    assert "ExecStart=/home/rlopez/inneros/inneros_core/platform/venv/bin/python -m inneros_core_runtime.mcp_server" in source
    assert "-m raphiia_openai.mcp_server" not in source
