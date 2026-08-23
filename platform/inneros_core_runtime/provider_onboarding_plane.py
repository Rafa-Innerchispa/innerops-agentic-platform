"""Provider onboarding plane for safe cloud/tool adapters.

This module stores declarative provider manifests only after validation. It does
not install packages or execute internet code; adapters must pass review/tests.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import mongo_store
from raphiia_openai.agent_auto_log import record_agent_run

AGENT_ID = "AG-44_PROVIDER_ONBOARDING"
MANIFEST_DIR = Path(os.getenv("RALFIA_PROVIDER_MANIFEST_DIR", "/home/rlopez/inneros/inneros_core/var/provider_manifests"))
AUDIT_COLLECTION = "ralfia_provider_onboarding_audit"
RISK_LEVELS = {"read_only", "low_write", "moderate_write", "high_write"}
AUTH_MODES = {"owner_vault", "oauth", "service_account", "api_key_server_side", "none"}


def provider_manifest_schema() -> dict[str, Any]:
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "schema_version": "provider_manifest_v1",
        "required": [
            "id",
            "label",
            "auth_mode",
            "secret_category",
            "capabilities",
            "risk_level",
            "allowed_resources",
            "rate_limits",
        ],
        "auth_modes": sorted(AUTH_MODES),
        "risk_levels": sorted(RISK_LEVELS),
        "common_interface": ["status", "preflight", "dry_run", "apply", "rollback", "audit"],
        "policy": [
            "No raw secrets in manifests.",
            "No arbitrary code install or execution from internet.",
            "Write/apply tools require allowlist plus approval_id.",
            "Every provider needs tests and evidence IDs before production use.",
        ],
    }


def provider_list_manifests() -> dict[str, Any]:
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    manifests = []
    for path in sorted(MANIFEST_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        manifests.append(_redact_manifest(data))
    return {"ok": True, "agent_id": AGENT_ID, "count": len(manifests), "manifests": manifests}


def provider_register_manifest(manifest: dict[str, Any], dry_run: bool = True, approval_id: str = "") -> dict[str, Any]:
    validation = _validate_manifest(manifest)
    if not validation["ok"]:
        return {"ok": False, "agent_id": AGENT_ID, "validation": validation}
    clean = validation["manifest"]
    path = MANIFEST_DIR / f"{clean['id']}.json"
    result = {
        "ok": True,
        "agent_id": AGENT_ID,
        "dry_run": dry_run,
        "manifest": _redact_manifest(clean),
        "path": str(path),
        "executed": False,
        "requires_approval_id_for_write": clean["risk_level"] != "read_only",
    }
    if dry_run:
        _audit("provider_register_manifest_dry_run", result)
        return result
    if clean["risk_level"] != "read_only" and not _valid_approval_id(approval_id):
        return {"ok": False, "agent_id": AGENT_ID, "error": "approval_id_required", "manifest": _redact_manifest(clean)}
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    clean["registered_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(clean, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["executed"] = True
    _audit("provider_register_manifest", result)
    return result


def provider_preflight(provider_id: str) -> dict[str, Any]:
    provider_id = _provider_id(provider_id)
    path = MANIFEST_DIR / f"{provider_id}.json"
    if not path.exists():
        return {"ok": False, "agent_id": AGENT_ID, "error": "provider_manifest_not_found", "provider_id": provider_id}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    checks = {
        "manifest_present": True,
        "auth_mode": manifest.get("auth_mode"),
        "secret_category_configured": bool(manifest.get("secret_category")) or manifest.get("auth_mode") == "none",
        "has_status_capability": "status" in manifest.get("capabilities", []),
        "has_dry_run_capability": "dry_run" in manifest.get("capabilities", []),
        "write_requires_approval": manifest.get("risk_level") != "read_only",
    }
    return {"ok": all(checks.values()), "agent_id": AGENT_ID, "provider_id": provider_id, "checks": checks, "manifest": _redact_manifest(manifest)}


def _validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        return {"ok": False, "error": "manifest_must_be_object"}
    provider_id = _provider_id(str(manifest.get("id", "")))
    if not provider_id:
        return {"ok": False, "error": "provider_id_invalid"}
    auth_mode = str(manifest.get("auth_mode", "")).strip()
    risk_level = str(manifest.get("risk_level", "")).strip()
    if auth_mode not in AUTH_MODES:
        return {"ok": False, "error": "auth_mode_invalid", "allowed": sorted(AUTH_MODES)}
    if risk_level not in RISK_LEVELS:
        return {"ok": False, "error": "risk_level_invalid", "allowed": sorted(RISK_LEVELS)}
    clean = {
        "id": provider_id,
        "label": str(manifest.get("label") or provider_id)[:120],
        "endpoints": _string_list(manifest.get("endpoints")),
        "cli": str(manifest.get("cli") or "")[:80],
        "sdk": str(manifest.get("sdk") or "")[:120],
        "auth_mode": auth_mode,
        "secret_category": str(manifest.get("secret_category") or "")[:120],
        "scopes": _string_list(manifest.get("scopes")),
        "capabilities": _string_list(manifest.get("capabilities")),
        "risk_level": risk_level,
        "allowed_resources": _string_list(manifest.get("allowed_resources")),
        "allowed_domains": _string_list(manifest.get("allowed_domains")),
        "rate_limits": manifest.get("rate_limits") if isinstance(manifest.get("rate_limits"), dict) else {},
        "common_interface": ["status", "preflight", "dry_run", "apply", "rollback", "audit"],
    }
    if _looks_sensitive(json.dumps(clean)):
        return {"ok": False, "error": "manifest_contains_secret_like_value"}
    return {"ok": True, "manifest": clean}


def _provider_id(value: str) -> str:
    value = (value or "").strip().lower()
    return value if re.fullmatch(r"[a-z][a-z0-9_-]{1,48}", value) else ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:180] for item in value if str(item).strip()][:100]


def _looks_sensitive(text: str) -> bool:
    return bool(re.search(r"(?i)(-----BEGIN|password\\s*[:=]|token\\s*[:=]|secret\\s*[:=]|api[_-]?key\\s*[:=])", text or ""))


def _redact_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in manifest.items() if k not in {"private_key", "token", "password", "api_key", "secret"}}


def _valid_approval_id(value: str) -> bool:
    return bool(re.fullmatch(r"(ops|msg|approval)_[A-Za-z0-9_-]{8,80}", (value or "").strip()))


def _audit(action: str, evidence: dict[str, Any]) -> None:
    try:
        mongo_store.get_db()[AUDIT_COLLECTION].insert_one(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "agent_id": AGENT_ID,
                "action": action,
                "evidence": evidence,
            }
        )
    except Exception:
        pass
    record_agent_run(AGENT_ID, action=action, summary=str(evidence.get("path", ""))[:80], project="ralfia-provider-onboarding")
