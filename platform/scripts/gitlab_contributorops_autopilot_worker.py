#!/usr/bin/env python3
"""Background worker for GitLab ContributorOps autopilot (repair / bootstrap)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from inneros_core_runtime import gitlab_contributorops_autopilot as autopilot  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", required=True, help="JSON payload with mode + event/issue_iid")
    args = parser.parse_args()
    payload = json.loads(args.payload)
    mode = str(payload.get("mode") or "repair")
    if mode == "repair":
        result = autopilot.repair_merge_request_event(payload.get("event") or {}, dry_run=False)
    elif mode == "bootstrap_issue":
        result = autopilot.bootstrap_quick_win_issue(int(payload["issue_iid"]), dry_run=False)
    else:
        result = {"ok": False, "error": "unknown_mode", "mode": mode}
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
