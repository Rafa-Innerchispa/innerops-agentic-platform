#!/usr/bin/env python3
"""Registra buzones personales/empresa adicionales en Mongo email_accounts.

Contraseñas (prioridad):
  1. Variable EMAIL_IMAP_<addr con _>@dominio  (ej. EMAIL_IMAP_rafagye_gmail_com)
  2. Archivo ~/.config/ralfia/email_secrets.json  {"rafagye@gmail.com": "app-pass"}
  3. Herencia hosting: innerchispa/innerspark ← rlopez@innerchispa.us; pcdoctor.ai ← info@pcdoctor.com.ec

Uso:
  PYTHONPATH=. venv/bin/python3 scripts/register_owner_email_accounts.py
  PYTHONPATH=. venv/bin/python3 scripts/register_owner_email_accounts.py --poll
"""

from __future__ import annotations

import argparse
import imaplib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from raphiia_openai import mongo_store  # noqa: E402

# Rafael — lista canónica solicitada 2026-08-13
TARGET_ACCOUNTS: tuple[dict[str, str], ...] = (
    {"address": "hrlg@hotmail.com", "label": "Rafael Hotmail", "password_ref": "env"},
    {"address": "rafagye@gmail.com", "label": "Rafael Gmail", "password_ref": "env"},
    {"address": "pcdoctorgye@gmail.com", "label": "PC Doctor Gmail", "password_ref": "env"},
    {"address": "rlopez@innerchispa.us", "label": "InnerChispa Rlopez", "password_ref": "existing"},
    {"address": "rlopez@innerspark.live", "label": "InnerSpark Rlopez", "password_ref": "innerchispa"},
    {"address": "info@innerchispa.us", "label": "Info InnerChispa", "password_ref": "innerchispa"},
    {"address": "info@innerspark.live", "label": "Info InnerSpark", "password_ref": "innerchispa"},
    {"address": "rlopez@pcdoctor.ai", "label": "Rlopez pcdoctor.ai", "password_ref": "pcdoctor"},
    {"address": "info@pcdoctor.ai", "label": "Info pcdoctor.ai", "password_ref": "pcdoctor"},
    {"address": "heralope@espol.edu.ec", "label": "ESPOL heralope", "password_ref": "env"},
)

IMAP_PRESETS: dict[str, dict[str, object]] = {
    "gmail.com": {"imap_host": "imap.gmail.com", "imap_port": 993},
    "hotmail.com": {"imap_host": "outlook.office365.com", "imap_port": 993},
    "innerchispa.us": {"imap_host": "mail.innerchispa.us", "imap_port": 993},
    "innerspark.live": {"imap_host": "mail.innerspark.live", "imap_port": 993},
    "pcdoctor.com.ec": {"imap_host": "mail.pcdoctor.com.ec", "imap_port": 993},
    "pcdoctor.ai": {"imap_host": "mail.pcdoctor.com.ec", "imap_port": 993},
    "espol.edu.ec": {"imap_host": "outlook.office365.com", "imap_port": 993},
}

SECRETS_FILE = Path.home() / ".config/ralfia/email_secrets.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _env_key(address: str) -> str:
    return "EMAIL_IMAP_" + re.sub(r"[^A-Za-z0-9]", "_", address).upper()


def _load_secrets_file() -> dict[str, str]:
    if not SECRETS_FILE.is_file():
        return {}
    try:
        data = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
        return {str(k).lower(): str(v) for k, v in data.items() if v}
    except Exception:
        return {}


def _imap_preset(address: str) -> dict[str, object]:
    domain = address.split("@")[-1].lower()
    base = IMAP_PRESETS.get(domain, {"imap_host": f"mail.{domain}", "imap_port": 993})
    return {"imap_host": str(base["imap_host"]), "imap_port": int(base["imap_port"])}


def _get_password(address: str, password_ref: str, db, secrets: dict[str, str]) -> tuple[str, str]:
    addr = address.lower()

    env_pw = os.environ.get(_env_key(addr), "").strip()
    if env_pw:
        return env_pw, "env"

    file_pw = secrets.get(addr, "").strip()
    if file_pw:
        return file_pw, "secrets_file"

    if password_ref == "existing":
        doc = db.email_accounts.find_one({"address": addr}) or {}
        pw = doc.get("imap_password") or ""
        return pw, "existing"

    ref_map = {
        "innerchispa": "rlopez@innerchispa.us",
        "pcdoctor": "info@pcdoctor.com.ec",
    }
    if password_ref in ref_map:
        ref = db.email_accounts.find_one({"address": ref_map[password_ref]}) or {}
        pw = ref.get("imap_password") or ""
        if pw:
            return pw, f"inherit:{ref_map[password_ref]}"

    return "", "missing"


def _test_imap(host: str, user: str, password: str, port: int = 993) -> tuple[bool, str]:
    if not password:
        return False, "sin contraseña"
    try:
        conn = imaplib.IMAP4_SSL(host, port, timeout=20)
        conn.login(user, password)
        conn.select("INBOX", readonly=True)
        conn.logout()
        return True, "ok"
    except imaplib.IMAP4.error as exc:
        return False, str(exc)[:160]
    except Exception as exc:
        return False, str(exc)[:160]


def _upsert_account(db, spec: dict[str, str], preset: dict[str, object], password: str, *, enabled: bool, note: str) -> dict:
    addr = spec["address"].lower()
    existing = db.email_accounts.find_one({"address": addr})
    doc = {
        "address": addr,
        "label": spec["label"],
        "imap_host": preset["imap_host"],
        "imap_port": preset["imap_port"],
        "imap_user": addr,
        "imap_folder": "INBOX",
        "enabled": enabled,
        "monitor_since": "2026-01-01",
        "whatsapp_numbers": [],
        "keywords": [],
        "updated_at": _now(),
        "last_error": "" if enabled else note,
    }
    if password:
        doc["imap_password"] = password
    if existing:
        db.email_accounts.update_one({"address": addr}, {"$set": doc})
        doc["email_account_id"] = existing.get("email_account_id")
        doc["action"] = "updated"
    else:
        import uuid

        eid = "eml_" + uuid.uuid4().hex[:12]
        doc.update(
            {
                "email_account_id": eid,
                "last_uid": 0,
                "last_poll_at": None,
                "created_at": _now(),
                "action": "created",
            }
        )
        db.email_accounts.insert_one(doc)
    public = {k: v for k, v in doc.items() if k != "imap_password"}
    public["has_password"] = bool(password)
    public["enabled"] = enabled
    public["note"] = note
    return public


def register(*, dry_run: bool = False) -> list[dict]:
    db = mongo_store.get_db()
    secrets = _load_secrets_file()
    results: list[dict] = []

    for spec in TARGET_ACCOUNTS:
        addr = spec["address"].lower()
        preset = _imap_preset(addr)
        password, pw_source = _get_password(addr, spec["password_ref"], db, secrets)
        ok, test_msg = _test_imap(preset["imap_host"], addr, password, int(preset["imap_port"]))
        enabled = ok
        note = test_msg if not ok else f"password:{pw_source}"

        row = {
            "address": addr,
            "imap_host": preset["imap_host"],
            "password_source": pw_source,
            "connection_ok": ok,
            "connection_msg": test_msg,
            "enabled": enabled,
        }
        if not dry_run and (password or spec["password_ref"] == "existing"):
            if spec["password_ref"] == "existing" and not password:
                existing = db.email_accounts.find_one({"address": addr}) or {}
                row["action"] = "skipped_existing"
                row["enabled"] = bool(existing.get("enabled"))
            else:
                saved = _upsert_account(db, spec, preset, password, enabled=enabled, note=note)
                row.update(saved)
        results.append(row)

    # trusted domains globales
    if not dry_run:
        extra_domains = [
            "innerchispa.us", "innerspark.live", "pcdoctor.ai",
            "gmail.com", "hotmail.com", "outlook.com",
        ]
        settings = db.email_settings.find_one({"_id": "global"}) or {}
        trusted = list(settings.get("trusted_domains") or [])
        for dom in extra_domains:
            if dom not in trusted:
                trusted.append(dom)
        db.email_settings.update_one({"_id": "global"}, {"$set": {"trusted_domains": trusted}}, upsert=True)

    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--poll", action="store_true", help="Poll Swarm tras registrar")
    args = parser.parse_args()

    rows = register(dry_run=args.dry_run)
    print(json.dumps(rows, indent=2, ensure_ascii=False, default=str))

    enabled_n = sum(1 for r in rows if r.get("enabled"))
    pending = [r["address"] for r in rows if not r.get("connection_ok")]
    print(f"\nResumen: {enabled_n}/{len(rows)} conectadas")
    if pending:
        print("Pendientes (app password o secrets):", ", ".join(pending))
        print(f"Opción A: {SECRETS_FILE}")
        print('Opción B: EMAIL_IMAP_rafagye_gmail_com="xxxx xxxx xxxx xxxx" python3 scripts/register_owner_email_accounts.py')

    if args.poll and not args.dry_run:
        import httpx

        r = httpx.post("http://127.0.0.1:8100/api/v1/email/poll", timeout=180.0)
        print("\nPoll:", r.json() if r.is_success else r.text[:300])


if __name__ == "__main__":
    main()
