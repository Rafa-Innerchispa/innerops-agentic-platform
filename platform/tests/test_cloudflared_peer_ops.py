from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "inneros_core_runtime" / "notifications" / "whatsapp_service_ops.py"
_spec = importlib.util.spec_from_file_location("cloudflared_peer_ops_fixture", MODULE_PATH)
assert _spec and _spec.loader
ops = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ops
_spec.loader.exec_module(ops)


def test_cloudflared_is_explicit_primary_only_service():
    spec = ops.SERVICE_BY_ID["cloudflared"]
    assert spec.kind == "user"
    assert spec.unit("primary") == "opportunityops-cloudflared.service"
    assert spec.unit("amd") is None
    assert ops.service_status("cloudflared", "amd")["error"] == "service_not_available_on_node"


def test_cloudflared_restart_uses_fixed_systemd_user_argv():
    before = {"ok": True, "healthy": False, "system_state": "active", "health": "down"}
    after = {"ok": True, "healthy": True, "system_state": "active", "health": "up"}
    proc = subprocess.CompletedProcess([], 0, "", "")
    with patch.object(ops, "service_status", side_effect=[before, after]), patch.object(
        ops, "_run_node", return_value=proc
    ) as runner, patch.object(ops.time, "sleep"):
        result = ops.execute_service_action("cloudflared", "primary", "restart")
    assert result["ok"] is True
    assert runner.call_args.args == (
        "primary",
        ["systemctl", "--user", "restart", "opportunityops-cloudflared.service"],
    )


def test_unknown_tunnel_service_stays_denied():
    result = ops.execute_service_action("cloudflared-arbitrary", "primary", "restart")
    assert result["ok"] is False
    assert result["error"] == "service_not_allowlisted"
