#!/usr/bin/env python3
"""Timer AG-53: scan correo hackathons + status funding."""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    from raphiia_openai.agents import ag53_hackathon_agent as ag53

    status = ag53.agent_hackathon_status()
    scan = ag53.agent_hackathon_scan_emails(limit=10)
    ok = bool(status.get("ok")) and bool(scan.get("ok"))
    print("ok=", ok, "programs=", len(status.get("hackathon_programs") or []), "email_hits=", scan.get("count"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
