"""Bóveda de credenciales del owner — cifrado at-rest, solo Rafael."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from raphiia_openai import mongo_store

COL = "ralfia_owner_vault"
OWNER = "RAFAEL"
KEY_FILE = Path(os.getenv("OWNER_VAULT_KEY_FILE", "/home/rlopez/.config/ralfia/vault.key"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fernet() -> Fernet:
    """Fail closed if a vault key is missing while encrypted records exist.

    Never generate a replacement key that would make saved credentials unreadable.
    Only an empty, reachable Mongo vault may be initialized with a new key.
    """
    raw = os.getenv("OWNER_VAULT_KEY", "").strip()
    if not raw and KEY_FILE.is_file():
        raw = KEY_FILE.read_text(encoding="utf-8").strip()
    if not raw:
        # A database outage is NOT proof of an empty vault. Let it raise.
        existing = mongo_store.get_db()[COL].find_one({"owner_id": OWNER}, {"_id": 1})
        if existing:
            raise RuntimeError("owner_vault_key_missing_existing_credentials")
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        generated = Fernet.generate_key().decode("ascii")
        try:
            fd = os.open(str(KEY_FILE), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            # Concurrent initializer won; do not overwrite its encryption key.
            raw = KEY_FILE.read_text(encoding="utf-8").strip()
        else:
            try:
                with os.fdopen(fd, "w", encoding="ascii") as fh:
                    fh.write(generated + "\n")
                raw = generated
            except Exception:
                KEY_FILE.unlink(missing_ok=True)
                raise
    if len(raw) != 44:
        # Preserve historic user-supplied passphrase format for backward
        # compatibility; never silently rotate or change an existing key.
        digest = hashlib.sha256(raw.encode("utf-8")).digest()
        raw = base64.urlsafe_b64encode(digest).decode("ascii")
    return Fernet(raw.encode("ascii"))


def _cred_id(category: str, key: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", f"{category}_{key}".lower()).strip("_")[:80]
    return f"cred_{slug}"


def save_owner_credential(
    *,
    key: str,
    secret: str,
    category: str = "general",
    label: str = "",
    metadata: dict[str, Any] | None = None,
    actor: str = OWNER,
) -> dict[str, Any]:
    key = key.strip().lower()
    if not key or not secret or not secret.strip():
        return {"ok": False, "error": "key_and_nonempty_secret_required"}
    if actor.upper() != OWNER:
        return {"ok": False, "error": "owner_only"}

    try:
        f = _fernet()
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc), "secret_returned": False}
    vault_id = _cred_id(category, key)
    db = mongo_store.get_db()
    # On a wrong/missing key, refuse to replace an encrypted entry: otherwise
    # the owner loses the previous (possibly still recoverable) credential.
    existing = db[COL].find_one({"vault_id": vault_id}, {"encrypted_secret": 1})
    old_blob = str((existing or {}).get("encrypted_secret") or "")
    if existing and old_blob:
        try:
            f.decrypt(old_blob.encode("ascii"))
        except (InvalidToken, UnicodeDecodeError, ValueError):
            return {"ok": False, "error": "existing_secret_key_mismatch",
                    "vault_id": vault_id, "secret_returned": False}
    doc = {
        "vault_id": vault_id,
        "owner_id": OWNER,
        "category": category.strip().lower(),
        "key": key,
        "label": label or key,
        "encrypted_secret": f.encrypt(secret.encode("utf-8")).decode("ascii"),
        "metadata": metadata or {},
        "privacy_scope": "PRIVATE_PERSONAL",
        "updated_at": _now(),
        "updated_by": actor.upper(),
    }
    db[COL].update_one({"vault_id": vault_id}, {"$set": doc, "$setOnInsert": {"created_at": _now()}}, upsert=True)

    # Never report success until the value can be read back and decrypted with
    # the active vault key. This prevents phantom/empty credential records.
    persisted = db[COL].find_one({"vault_id": vault_id}, {"_id": 0, "encrypted_secret": 1})
    recovered = ""
    try:
        blob = str((persisted or {}).get("encrypted_secret") or "")
        recovered = f.decrypt(blob.encode("ascii")).decode("utf-8") if blob else ""
    except (InvalidToken, UnicodeDecodeError, ValueError):
        recovered = ""
    if not recovered or not hmac.compare_digest(recovered, secret):
        return {
            "ok": False,
            "error": "persistence_verification_failed",
            "vault_id": vault_id,
            "key": key,
            "category": category.strip().lower(),
        }

    return {
        "ok": True,
        "vault_id": vault_id,
        "key": key,
        "category": category.strip().lower(),
        "label": doc["label"],
        "verified_persisted": True,
    }


def _decrypt(blob: str) -> str:
    try:
        return _fernet().decrypt(blob.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return ""


def get_owner_credential(
    key: str,
    *,
    category: str = "",
    reveal: bool = True,
    actor: str = OWNER,
) -> dict[str, Any]:
    if actor.upper() != OWNER:
        return {"ok": False, "error": "owner_only"}
    key = key.strip().lower()
    db = mongo_store.get_db()
    filt: dict[str, Any] = {"owner_id": OWNER, "key": key}
    if category:
        filt["category"] = category.strip().lower()
    doc = db[COL].find_one(filt, {"_id": 0})
    if not doc:
        return {"ok": False, "error": "not_found", "key": key}
    out = {
        "ok": True,
        "vault_id": doc.get("vault_id"),
        "key": doc.get("key"),
        "category": doc.get("category"),
        "label": doc.get("label"),
        "metadata": doc.get("metadata") or {},
        "updated_at": doc.get("updated_at"),
    }
    if reveal:
        try:
            recovered = _decrypt(str(doc.get("encrypted_secret") or ""))
        except RuntimeError:
            recovered = ""
        if not recovered:
            return {
                **out, "ok": False,
                "error": "vault_decryption_failed",
                "secret_returned": False,
            }
        out["secret"] = recovered
    return out


def list_owner_credentials(
    *,
    category: str = "",
    reveal: bool = False,
    actor: str = OWNER,
) -> dict[str, Any]:
    if actor.upper() != OWNER:
        return {"ok": False, "error": "owner_only"}
    filt: dict[str, Any] = {"owner_id": OWNER}
    if category:
        filt["category"] = category.strip().lower()
    rows = list(mongo_store.get_db()[COL].find(filt, {"_id": 0}).sort("category", 1))
    items: list[dict[str, Any]] = []
    for doc in rows:
        item = {
            "vault_id": doc.get("vault_id"),
            "key": doc.get("key"),
            "category": doc.get("category"),
            "label": doc.get("label"),
            "metadata": doc.get("metadata") or {},
            "updated_at": doc.get("updated_at"),
        }
        if reveal:
            item["secret"] = _decrypt(str(doc.get("encrypted_secret") or ""))
        items.append(item)
    return {"ok": True, "count": len(items), "items": items}


def import_email_accounts_to_vault(*, actor: str = OWNER) -> dict[str, Any]:
    """Importa email_accounts (IMAP) + email_secrets.json → bóveda cifrada."""
    if actor.upper() != OWNER:
        return {"ok": False, "error": "owner_only"}
    imported = 0
    db = mongo_store.get_db()
    for acc in db.email_accounts.find({}, {"_id": 0}):
        addr = str(acc.get("address") or "").lower()
        pw = str(acc.get("imap_password") or "").strip()
        if not addr or not pw:
            continue
        save_owner_credential(
            key=addr,
            secret=pw,
            category="email_imap",
            label=str(acc.get("label") or addr),
            metadata={
                "imap_host": acc.get("imap_host"),
                "imap_port": acc.get("imap_port", 993),
                "enabled": acc.get("enabled", False),
            },
            actor=actor,
        )
        imported += 1

    secrets_path = Path.home() / ".config/ralfia/email_secrets.json"
    if secrets_path.is_file():
        try:
            data = json.loads(secrets_path.read_text(encoding="utf-8"))
            for addr, pw in data.items():
                if not addr or not pw:
                    continue
                save_owner_credential(
                    key=str(addr).lower(),
                    secret=str(pw),
                    category="email_imap",
                    label=str(addr),
                    metadata={"source": "email_secrets.json"},
                    actor=actor,
                )
                imported += 1
        except (OSError, json.JSONDecodeError):
            pass

    return {"ok": True, "imported": imported, "collection": COL}


def get_owner_vault_summary(*, actor: str = OWNER) -> dict[str, Any]:
    """Resumen para Rafael — categorías, cuentas, sin exponer secretos en logs MCP por defecto."""
    listed = list_owner_credentials(actor=actor, reveal=False)
    if not listed.get("ok"):
        return listed
    by_cat: dict[str, list[str]] = {}
    for item in listed.get("items") or []:
        cat = str(item.get("category") or "general")
        by_cat.setdefault(cat, []).append(str(item.get("key") or ""))
    return {
        "ok": True,
        "owner_id": OWNER,
        "total": listed.get("count", 0),
        "by_category": {k: len(v) for k, v in by_cat.items()},
        "keys_by_category": by_cat,
        "hint": "Usa get_owner_credential(key=..., reveal=true) para el valor.",
    }
