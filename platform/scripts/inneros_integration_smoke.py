#!/usr/bin/env python3
"""Unified InnerOS integration smoke — MCP + ACP + IDE bridge + KPI."""
from __future__ import annotations

import json
import sys
from pathlib import Path

PLATFORM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM))

from inneros_core_runtime import ide_task_bridge, inneros_agent_fabric  # noqa: E402
from inneros_core_runtime.agents import ag58_acp_deliverable_tracker as ag58  # noqa: E402


def main() -> int:
    store: ide_task_bridge.DispatchStore = {}
    payload = {
        "fabric": inneros_agent_fabric.fabric_status(),
        "harmonized_dispatch_codex": inneros_agent_fabric.harmonized_dispatch(
            title="Integration probe",
            body="InnerOS fabric harmonized dispatch",
            target="codex",
            correlation_id="inneros-integration-smoke-20260829",
            ops_task_id="ops_eb79b6f51bb0",
            dry_run=True,
            store=store,
        ),
        "acp": ag58.deliverable_status(),
        "cursor_acp": ag58.probe_cursor_acp_surface(),
    }
    print(json.dumps(payload, indent=2, default=str))
    fabric_ok = payload["fabric"].get("status") == "OK"
    dispatch_ok = payload["harmonized_dispatch_codex"].get("ok")
    return 0 if fabric_ok and dispatch_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
