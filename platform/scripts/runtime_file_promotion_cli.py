"""One-shot CLI for runtime_file_promotion.

The request file is intentionally fixed beside this script. It is deleted after
one execution so an approval token cannot be replayed accidentally.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from inneros_core_runtime import runtime_file_promotion as promotion

REQUEST_PATH = Path(__file__).with_name("runtime_file_promotion.request.json")


def main() -> int:
    if not REQUEST_PATH.is_file():
        print(json.dumps({"ok": False, "error": "request_file_missing", "path": str(REQUEST_PATH)}, sort_keys=True))
        return 2
    try:
        payload = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": "request_file_invalid", "detail": str(exc)}, sort_keys=True))
        return 3

    try:
        action = str(payload.pop("action", "")).strip().lower()
        if action == "plan":
            result = promotion.plan_promotion(**payload)
        elif action == "apply":
            result = promotion.apply_promotion(**payload)
        elif action == "patch_plan":
            result = promotion.plan_text_patch(**payload)
        elif action == "patch_apply":
            result = promotion.apply_text_patch(**payload)
        elif action == "rollback":
            result = promotion.rollback_promotion(**payload)
        else:
            result = {
                "ok": False,
                "error": "action_not_allowlisted",
                "allowed": ["plan", "apply", "patch_plan", "patch_apply", "rollback"],
            }
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("ok") else 4
    finally:
        try:
            REQUEST_PATH.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
