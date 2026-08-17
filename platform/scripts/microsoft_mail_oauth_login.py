#!/usr/bin/env python3
"""Login OAuth Microsoft para correo — device code (desde Windows del owner)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from raphiia_openai.notifications import microsoft_mail_oauth as ms  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="OAuth Microsoft mail (Hotmail / ESPOL)")
    p.add_argument("email", nargs="?", default="", help="hrlg@hotmail.com o heralope@espol.edu.ec")
    p.add_argument("--tenant", default="common", help="common | espol.edu.ec")
    p.add_argument("--complete", metavar="SESSION_ID", help="Completar sesión device code")
    p.add_argument("--status", action="store_true")
    args = p.parse_args()

    if args.status:
        print(json.dumps(ms.oauth_config_status(), indent=2))
        return

    if not args.email:
        print("email requerido (ej. hrlg@hotmail.com)", file=sys.stderr)
        sys.exit(1)

    if args.complete:
        r = ms.complete_device_login(args.complete, timeout_sec=300)
        print(json.dumps(r, indent=2, default=str))
        return

    r = ms.start_device_login(email=args.email, tenant=args.tenant)
    print(json.dumps(r, indent=2, ensure_ascii=False))
    if r.get("ok"):
        print("\n>>> Abre en tu Windows:", r.get("verification_uri"))
        print(">>> Código:", r.get("user_code"))
        print(">>> Luego:", f"PYTHONPATH=. venv/bin/python3 scripts/microsoft_mail_oauth_login.py {args.email} --complete {r.get('session_id')}")


if __name__ == "__main__":
    main()
