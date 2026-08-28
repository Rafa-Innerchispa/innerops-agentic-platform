#!/usr/bin/env python3
"""ACP/IDE Fabric smoke for ops_608d9780a8dd."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PLATFORM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM))

from inneros_core_runtime.agents import ag58_acp_deliverable_tracker as ag58  # noqa: E402


def main() -> int:
    payload = {
        "matrix": ag58.capability_matrix(),
        "deliverable": ag58.deliverable_status(),
        "cursor_acp": ag58.probe_cursor_acp_surface(),
        "codex_adapter": ag58.verified_adapter_smoke(target="codex"),
    }
    print(json.dumps(payload, indent=2, default=str))
    status = payload["deliverable"].get("status")
    return 0 if status == "OK" else 2


if __name__ == "__main__":
    raise SystemExit(main())
