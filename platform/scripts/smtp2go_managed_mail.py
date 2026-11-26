#!/usr/bin/env python3
"""Trusted owner CLI: SMTP2GO management without exposing a new public HTTP service."""
import argparse
import json
import sys
from pathlib import Path
from dotenv import load_dotenv

PLATFORM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM))
load_dotenv(PLATFORM / '.env', override=False)
from inneros_core_runtime.smtp2go_service import ManagedMail, SMTP2GOError, redact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list-clients")
    for action in ["status", "activity", "auth-check", "ensure-domain", "ensure-smtp-user"]:
        p = sub.add_parser(action); p.add_argument("client_id")
        if action.startswith("ensure-"): p.add_argument("--apply", action="store_true")
    p = sub.add_parser("register"); p.add_argument("client_id"); p.add_argument("--subaccount-id", required=True); p.add_argument("--domain", required=True); p.add_argument("--apply", action="store_true")
    p = sub.add_parser("create-client"); p.add_argument("client_id"); p.add_argument("--name", required=True); p.add_argument("--domain", required=True); p.add_argument("--cycle-limit", required=True, type=int); p.add_argument("--apply", action="store_true")
    p = sub.add_parser("update-client"); p.add_argument("client_id"); p.add_argument("--name"); p.add_argument("--cycle-limit", type=int); p.add_argument("--apply", action="store_true")
    a = parser.parse_args(); service = ManagedMail.from_owner_vault()
    if a.action == "list-clients": result = service.clients()
    elif a.action == "status": result = service.status(a.client_id)
    elif a.action == "activity": result = service.activity(a.client_id)
    elif a.action == "auth-check": result = service.auth_check(a.client_id)
    elif a.action == "ensure-domain": result = service.ensure_domain(a.client_id, apply=a.apply)
    elif a.action == "ensure-smtp-user": result = service.ensure_smtp_user(a.client_id, apply=a.apply)
    elif a.action == "register": result = service.register(a.client_id, a.subaccount_id, a.domain, apply=a.apply)
    elif a.action == "create-client": result = service.create_client(a.client_id, a.name, a.domain, cycle_limit=a.cycle_limit, apply=a.apply)
    else: result = service.update_client(a.client_id, name=a.name, cycle_limit=a.cycle_limit, apply=a.apply)
    print(json.dumps(redact(result), default=str, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (SMTP2GOError, ValueError, LookupError, PermissionError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        raise SystemExit(1)
