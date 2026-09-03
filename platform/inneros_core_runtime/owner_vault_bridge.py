"""Safe generic owner-vault bridge for MCP and project runtime secrets.

The encrypted owner_vault already exists. This module exposes bounded operations
that never return plaintext secrets to MCP callers.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from inneros_core_runtime import owner_vault

_OWNER = "RAFAEL"
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,79}$")
_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")


def _clean_name(value: str, field: str) -> str:
    clean = (value or "").strip().lower()
    if not _NAME_RE.fullmatch(clean):
        raise ValueError(f"invalid_{field}")
    return clean


def _secret_ref(category: str, key: str) -> str:
    return f"owner_vault:{category}/{key}"


def store_secret(*, category: str, key: str, secret: str, label: str = "", project_id: str = "", actor: str = _OWNER) -> dict[str, Any]:
    """Encrypt one owner secret and return only a reference/metadata."""
    clean_category = _clean_name(category, "category")
    clean_key = _clean_name(key, "key")
    clean_project = _clean_name(project_id, "project_id") if project_id else ""
    if actor.upper() != _OWNER:
        return {"ok": False, "error": "owner_only", "secret_returned": False}
    if not secret:
        return {"ok": False, "error": "secret_required", "secret_returned": False}
    result = owner_vault.save_owner_credential(
        key=clean_key,
        secret=secret,
        category=clean_category,
        label=(label or clean_key)[:120],
        metadata={"project_id": clean_project, "source": "generic_owner_vault_bridge"},
        actor=actor,
    )
    return {
        "ok": bool(result.get("ok")),
        "secret_ref": _secret_ref(clean_category, clean_key) if result.get("ok") else None,
        "vault_id": result.get("vault_id"),
        "category": clean_category,
        "key": clean_key,
        "project_id": clean_project or None,
        "secret_returned": False,
    }


def secret_status(*, category: str, key: str, actor: str = _OWNER) -> dict[str, Any]:
    """Return presence and metadata only; plaintext is never returned."""
    clean_category = _clean_name(category, "category")
    clean_key = _clean_name(key, "key")
    if actor.upper() != _OWNER:
        return {
            "ok": False,
            "present": False,
            "error": "owner_only",
            "category": clean_category,
            "key": clean_key,
            "secret_returned": False,
        }
    result = owner_vault.get_owner_credential(clean_key, category=clean_category, reveal=False, actor=actor)
    if not result.get("ok"):
        return {"ok": False, "present": False, "error": result.get("error"), "category": clean_category, "key": clean_key, "secret_returned": False}
    return {
        "ok": True,
        "present": True,
        "secret_ref": _secret_ref(clean_category, clean_key),
        "vault_id": result.get("vault_id"),
        "category": clean_category,
        "key": clean_key,
        "label": result.get("label"),
        "metadata": result.get("metadata") or {},
        "updated_at": result.get("updated_at"),
        "secret_returned": False,
    }


def materialize_project_env(*, namespace: str, bindings: dict[str, str], static_values: dict[str, str] | None = None, actor: str = _OWNER) -> dict[str, Any]:
    """Write chmod-0600 runtime env from vault refs without returning secrets."""
    if actor.upper() != _OWNER:
        return {"ok": False, "error": "owner_only", "secret_returned": False}
    clean_namespace = _clean_name(namespace, "namespace")
    if not bindings:
        return {"ok": False, "error": "bindings_required", "secret_returned": False}
    lines: list[str] = []
    materialized: list[str] = []
    for env_name, ref in sorted(bindings.items()):
        if not _ENV_RE.fullmatch(str(env_name or "")):
            return {"ok": False, "error": "invalid_env_name", "env_name": env_name, "secret_returned": False}
        text_ref = str(ref or "").strip()
        payload = text_ref[len("owner_vault:"):] if text_ref.startswith("owner_vault:") else ""
        if "/" not in payload:
            return {"ok": False, "error": "invalid_secret_ref", "env_name": env_name, "secret_returned": False}
        category, key = payload.split("/", 1)
        category = _clean_name(category, "category")
        key = _clean_name(key, "key")
        cred = owner_vault.get_owner_credential(key, category=category, reveal=True, actor=actor)
        value = str(cred.get("secret") or "") if cred.get("ok") else ""
        if not value:
            return {"ok": False, "error": "secret_ref_unavailable", "secret_ref": _secret_ref(category, key), "env_name": env_name, "secret_returned": False}
        if "\n" in value or "\r" in value:
            return {"ok": False, "error": "multiline_secret_not_supported", "env_name": env_name, "secret_returned": False}
        lines.append(f"{env_name}={value}")
        materialized.append(env_name)
    static_keys: list[str] = []
    for env_name, value in sorted((static_values or {}).items()):
        if not _ENV_RE.fullmatch(str(env_name or "")):
            return {"ok": False, "error": "invalid_env_name", "env_name": env_name, "secret_returned": False}
        text = str(value)
        if "\n" in text or "\r" in text:
            return {"ok": False, "error": "multiline_static_value_not_supported", "env_name": env_name, "secret_returned": False}
        lines.append(f"{env_name}={text}")
        static_keys.append(env_name)
    target_dir = Path.home() / ".config" / clean_namespace
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "runtime.env"
    temp = target.with_suffix(".env.tmp")
    temp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temp.chmod(0o600)
    os.replace(temp, target)
    target.chmod(0o600)
    return {"ok": True, "path": str(target), "namespace": clean_namespace, "materialized_env_keys": materialized, "static_env_keys": static_keys, "secret_returned": False, "mode": "0600"}
