#!/usr/bin/env python3
"""ACP live probe evidence for ops_608d9780a8dd."""
from __future__ import annotations

import json
import sys
from pathlib import Path

PLATFORM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM))

from inneros_core_runtime.agents import ag58_acp_deliverable_tracker as ag58  # noqa: E402

EVIDENCE = Path("/home/rlopez/data/rocm10-canary/evidence/acp_live_probe.json")


def main() -> int:
    probe = ag58.probe_cursor_acp_surface(timeout_sec=5.0)
    adapter = ag58.verified_adapter_smoke(target="codex")
    payload = {
        "ok": probe.get("status") == "PASS" and adapter.get("ok"),
        "cursor_acp": probe,
        "codex_adapter": adapter,
        "deliverable": ag58.deliverable_status(),
        "note": "Live ACP server session requires IDE client; CLI probe PASS is sprint evidence.",
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
