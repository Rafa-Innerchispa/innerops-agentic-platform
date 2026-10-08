from __future__ import annotations

import sys
from pathlib import Path

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from inneros_core_runtime import agent_provider_registry as apr


def test_register_new_agent_z():
    out = apr.register_interactive_provider("agente_z", default_lane="agente_z_interactive")
    assert out["ok"] is True
    assert "agente_z" in apr.interactive_providers()
    lane, prov, do_not = apr.apply_create_ops_defaults("agente_z", execution_lane=None, preferred_provider=None, do_not_auto_dispatch=None)
    assert prov == "agente_z"
    assert do_not is True
