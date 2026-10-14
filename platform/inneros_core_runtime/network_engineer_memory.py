"""Persistent memory and recovery manifests for the InnerOS Network Engineer Agent.

Operational truth lives in MongoDB. Git exports are deliberately sanitized and
must never contain credentials or plaintext private topology. Full recovery
comes from encrypted disaster recovery (Mongo + owner_vault + vault key).
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from inneros_core_runtime import mongo_store

COL_FACTS = "network_engineer_site_facts"
COL_FINDINGS = "network_engineer_findings"
COL_SNAPSHOTS = "network_engineer_snapshots"

_SECRET_KEY_RE = re.compile(
    r"(secret|password|passwd|token|authorization|api[_-]?key|private[_-]?key|credential)",
    re.I,
)
_PRIVATE_TOPOLOGY_KEY_RE = re.compile(
    r"^(ip|ipv4|ipv6|cidr|subnet|gateway|mac|serial|serial_number|bssid|ssid_key|"
    r"management_ip|wan_ip|public_ip|endpoint)$",
    re.I,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_site_id(site_id: str) -> str:
    value = str(site_id or "").strip().lower()
    if not value or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,79}", value):
        raise ValueError("invalid_site_id")
    return value


def _clean_fact_key(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text or not re.fullmatch(r"[a-z0-9][a-z0-9_.:-]{0,119}", text):
        raise ValueError("invalid_fact_key")
    return text


def _assert_no_secret_material(value: Any, path: str = "value") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if _SECRET_KEY_RE.search(str(key)):
                text = str(child or "").strip()
                if text and not text.startswith(("owner_vault:", "credential_ref:", "vault:")):
                    raise ValueError(f"plaintext_secret_forbidden:{path}.{key}")
            _assert_no_secret_material(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            _assert_no_secret_material(child, f"{path}[{idx}]")


def save_site_fact(
    *,
    site_id: str,
    fact_key: str,
    value: Any,
    source: str,
    confidence: float = 1.0,
    actor: str = "network_engineer",
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Upsert one durable site fact with source/provenance and no plaintext secrets."""
    site = _clean_site_id(site_id)
    key = _clean_fact_key(fact_key)
    _assert_no_secret_material(value)
    now = _now()
    doc = {
        "site_id": site,
        "fact_key": key,
        "value": value,
        "source": str(source or "unknown")[:160],
        "confidence": max(0.0, min(float(confidence), 1.0)),
        "actor": str(actor or "network_engineer")[:80],
        "provenance": provenance or {},
        "updated_at": now,
    }
    db = mongo_store.get_db()
    db[COL_FACTS].update_one(
        {"site_id": site, "fact_key": key},
        {"$set": doc, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return {"ok": True, **doc}


def save_finding(
    *,
    site_id: str,
    code: str,
    severity: str,
    summary: str,
    evidence: dict[str, Any],
    status: str = "open",
    remediation: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Persist a network finding. Evidence may contain topology but never secrets."""
    site = _clean_site_id(site_id)
    finding_code = _clean_fact_key(code)
    _assert_no_secret_material(evidence, "evidence")
    _assert_no_secret_material(remediation or {}, "remediation")
    now = _now()
    doc = {
        "site_id": site,
        "code": finding_code,
        "severity": str(severity or "info").lower(),
        "summary": str(summary or "").strip(),
        "evidence": evidence,
        "status": str(status or "open").lower(),
        "remediation": remediation or {},
        "correlation_id": correlation_id,
        "updated_at": now,
    }
    db = mongo_store.get_db()
    db[COL_FINDINGS].update_one(
        {"site_id": site, "code": finding_code, "status": {"$ne": "superseded"}},
        {"$set": doc, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return {"ok": True, **doc}


def save_snapshot(
    *,
    site_id: str,
    snapshot_type: str,
    data: dict[str, Any],
    source: str,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Append an immutable operational snapshot and its content hash."""
    site = _clean_site_id(site_id)
    stype = _clean_fact_key(snapshot_type)
    _assert_no_secret_material(data, "snapshot")
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    doc = {
        "site_id": site,
        "snapshot_type": stype,
        "data": data,
        "sha256": digest,
        "source": str(source or "unknown")[:160],
        "correlation_id": correlation_id,
        "observed_at": _now(),
    }
    result = mongo_store.get_db()[COL_SNAPSHOTS].insert_one(dict(doc))
    return {"ok": True, "snapshot_id": str(result.inserted_id), **{k: v for k, v in doc.items() if k != "data"}}


def get_site_dossier(site_id: str, *, finding_limit: int = 100, snapshot_limit: int = 20) -> dict[str, Any]:
    """Return full internal site knowledge. Intended for authorized InnerOS callers."""
    site = _clean_site_id(site_id)
    db = mongo_store.get_db()
    facts = list(db[COL_FACTS].find({"site_id": site}, {"_id": 0}).sort("fact_key", 1))
    findings = list(
        db[COL_FINDINGS].find({"site_id": site}, {"_id": 0})
        .sort("updated_at", -1)
        .limit(max(1, min(int(finding_limit), 500)))
    )
    snapshots = list(
        db[COL_SNAPSHOTS].find({"site_id": site}, {"_id": 0, "data": 0})
        .sort("observed_at", -1)
        .limit(max(1, min(int(snapshot_limit), 100)))
    )
    return {
        "ok": True,
        "site_id": site,
        "facts": facts,
        "findings": findings,
        "snapshot_index": snapshots,
        "generated_at": _now(),
    }


def _git_safe(value: Any, key: str = "") -> Any:
    """Remove secret material and private topology from a Git recovery manifest."""
    if _SECRET_KEY_RE.search(key):
        text = str(value or "")
        if text.startswith(("owner_vault:", "credential_ref:", "vault:")):
            return text
        return "[REDACTED]"
    if _PRIVATE_TOPOLOGY_KEY_RE.fullmatch(key or ""):
        return "[PRIVATE_TOPOLOGY_IN_ENCRYPTED_DR]"
    if isinstance(value, dict):
        return {str(k): _git_safe(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_git_safe(v, key) for v in value]
    return value


def build_git_recovery_manifest(site_id: str) -> dict[str, Any]:
    """Build a sanitized, versionable manifest.

    This manifest is useful to rebuild adapters, roles, known models, findings,
    and snapshot hashes. Exact private topology and secrets remain in encrypted DR.
    """
    dossier = get_site_dossier(site_id)
    safe = _git_safe(dossier)
    safe["recovery_contract"] = {
        "operational_truth": "MongoDB / InnerOS",
        "secrets": "owner_vault only",
        "full_private_restore": "encrypted disaster recovery",
        "git_role": "code + schemas + sanitized site manifest + snapshot hashes",
        "plaintext_secrets_in_git": False,
        "plaintext_private_topology_in_git": False,
    }
    payload = json.dumps(safe, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    safe["manifest_sha256"] = hashlib.sha256(payload).hexdigest()
    return safe


def write_git_recovery_manifest(site_id: str, output_path: str | Path) -> dict[str, Any]:
    manifest = build_git_recovery_manifest(site_id)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"ok": True, "path": str(path), "sha256": manifest["manifest_sha256"], "site_id": manifest["site_id"]}
