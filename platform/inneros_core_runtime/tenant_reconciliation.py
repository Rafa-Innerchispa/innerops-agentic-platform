"""Read-only tenant/client reconciliation for Workforce and VigilOS migrations."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import mongo_store

REPORT_COLLECTION = "inneros_tenant_reconciliation_reports"
TARGETS = {
    "femar": {"label": "FEMAR S.A.", "tax_id": "0992364866001", "expected_ops_client_id": "client_6a73aaecf8906347e436916b"},
    "pcdoctor": {"label": "PC DOCTOR S.A.", "tax_id": "0992418575001", "expected_ops_client_id": "client_6a538b56ef22fd5dd79e3e62"},
    "ia_pro": {"label": "IA PRO", "tax_id": "", "draft_id": "clientdraft_6a8bc53b481eb6e2621dbf50"},
    "bellini_i_ii": {"label": "TORRES BELLINI I-II", "tax_id": "0992944714001"},
    "bellini_iii_iv": {"label": "EDIFICIO TORRES BELLINI III-IV", "tax_id": "0992992050001"},
}
COLLECTIONS = [
    "ops_clients",
    "clients",
    "crm_parties",
    "crm_identity_map",
    "app_users",
    "client_hubs",
    "workforce_tenants",
    "tenants",
    "users",
    "roles",
    "employees",
    "devices",
    "biometric_mappings",
    "credentials",
    "access_devices",
    "vigil_clients",
]
WORKFORCE_PATHS = [
    "/home/rlopez/projects/innerspark-workforce-ai",
    "/home/rlopez/projects/innerspark-workforce-connect",
    "/home/rlopez/worktrees/innerspark-workforce-ai-stabilization",
]
VIGILOS_PATHS = [
    "/home/rlopez/data/google_drive/Proyectos/hackaton vigilos/VigilOS_Cursor",
    "/home/rlopez/data/google_drive/Proyectos/hackaton vigilos/VigilOS_Cursor - Antigravity",
    "/home/rlopez/data/google_drive_archive/Proyectos/hackaton vigilos/VigilOS_Cursor",
    "/home/rlopez/data/google_drive_archive/Proyectos/hackaton vigilos/VigilOS_Cursor - Antigravity",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_doc(doc: dict[str, Any]) -> dict[str, Any]:
    blocked = re.compile(r"(?i)(password|secret|token|hash|credential|session|api[_-]?key)")
    out = {}
    for key, value in doc.items():
        if key == "_id":
            out[key] = str(value)
        elif blocked.search(str(key)):
            out[key] = "<redacted>"
        elif isinstance(value, str) and len(value) > 500:
            out[key] = value[:500] + "...<truncated>"
        else:
            out[key] = value
    return out


def _search_collection(col: str, target: dict[str, str]) -> dict[str, Any]:
    db = mongo_store.get_db()
    try:
        count = db[col].count_documents({})
    except Exception as exc:
        return {"collection": col, "error": str(exc), "count": 0, "matches": []}
    ors: list[dict[str, Any]] = []
    label = target.get("label", "")
    tax_id = target.get("tax_id", "")
    draft_id = target.get("draft_id", "")
    if tax_id:
        ors.extend([{field: tax_id} for field in ["tax_id", "ruc"]])
    if draft_id:
        ors.extend([{field: draft_id} for field in ["draft_id", "client_id"]])
    if label:
        for field in ["name", "display_name", "legal_name", "trade_name", "client_name", "tenant_name", "notes", "notas"]:
            ors.append({field: {"$regex": re.escape(label), "$options": "i"}})
        if label == "IA PRO":
            ors.extend([{field: {"$regex": r"\\bIA\\s*PRO\\b", "$options": "i"}} for field in ["name", "display_name", "legal_name", "tenant_name", "notes", "notas"]])
    if not ors:
        return {"collection": col, "count": count, "matches": []}
    try:
        docs = list(db[col].find({"$or": ors}, {"_id": 0}).limit(20))
    except Exception as exc:
        return {"collection": col, "count": count, "error": str(exc), "matches": []}
    return {"collection": col, "count": count, "matches": [_safe_doc(d) for d in docs]}


def _repo_hits(paths: list[str], target: dict[str, str]) -> list[dict[str, Any]]:
    patterns = [target.get("label", ""), target.get("tax_id", "")]
    if target.get("label") == "IA PRO":
        patterns += ["iapro", "ia pro", "IA_PRO"]
    hits = []
    rg = shutil.which("rg")
    for raw in paths:
        root = Path(raw)
        if not root.exists():
            continue
        if rg:
            expr = "|".join(re.escape(p) for p in patterns if p)
            if not expr:
                continue
            try:
                proc = subprocess.run(
                    [rg, "-n", "-i", "-m", "20", "--glob", "!*.{png,jpg,jpeg,gif,pdf,zip,sqlite,db}", expr, str(root)],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                for line in proc.stdout.splitlines()[:30]:
                    parts = line.split(":", 2)
                    hits.append({"path": parts[0], "line": parts[1] if len(parts) > 1 else "", "matched": [target.get("label", "")]})
                if len(hits) >= 30:
                    return hits
                continue
            except Exception:
                hits.append({"path": str(root), "matched": [], "note": "repo_scan_timeout_or_failed"})
                continue
        scanned = 0
        for path in root.rglob("*"):
            scanned += 1
            if scanned > 1200:
                break
            if not path.is_file() or path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".sqlite", ".db"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")[:200000]
            except Exception:
                continue
            matched = [p for p in patterns if p and re.search(re.escape(p), text, re.I)]
            if matched:
                hits.append({"path": str(path), "matched": matched[:5]})
                if len(hits) >= 30:
                    return hits
    return hits


def build_tenant_reconciliation_report(save: bool = True) -> dict[str, Any]:
    report: dict[str, Any] = {
        "ok": True,
        "report_id": f"tenant_reconciliation_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "generated_at": _now(),
        "mode": "read_only_no_migration",
        "targets": {},
        "rules": {
            "no_duplicate_tenants": True,
            "no_wipe": True,
            "no_reseed": True,
            "no_password_regeneration": True,
            "secrets_redacted": True,
            "bellini_i_ii_separate_from_iii_iv": True,
        },
    }
    for key, target in TARGETS.items():
        collections = [_search_collection(col, target) for col in COLLECTIONS]
        matches = [m for m in collections if m.get("matches")]
        ops_ids = []
        for row in matches:
            if row["collection"] == "ops_clients":
                ops_ids.extend(str(d.get("client_id") or d.get("draft_id") or "") for d in row.get("matches") or [])
        repo_paths = WORKFORCE_PATHS if key in {"femar", "pcdoctor", "ia_pro"} else VIGILOS_PATHS
        report["targets"][key] = {
            "expected": target,
            "canonical_candidates": sorted({x for x in ops_ids if x}),
            "collections": collections,
            "repo_hits": _repo_hits(repo_paths, target),
            "status": _target_status(key, target, matches),
        }
    report["summary"] = _summary(report)
    if save:
        mongo_store.get_db()[REPORT_COLLECTION].insert_one(json.loads(json.dumps(report, default=str)))
    return report


def _target_status(key: str, target: dict[str, str], matches: list[dict[str, Any]]) -> str:
    if key == "ia_pro":
        has_real = any(
            row["collection"] != "ops_clients" or any(str(d.get("status") or "").lower() != "draft" for d in row.get("matches") or [])
            for row in matches
        )
        return "needs_owner_or_workforce_repo_confirmation" if not has_real else "candidate_found_review_required"
    expected = target.get("expected_ops_client_id")
    if expected:
        found = any(any(d.get("client_id") == expected for d in row.get("matches") or []) for row in matches if row["collection"] == "ops_clients")
        return "confirmed" if found else "expected_ops_client_missing"
    return "confirmed" if matches else "not_found"


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    targets = report.get("targets") or {}
    return {
        "confirmed": [k for k, v in targets.items() if v.get("status") == "confirmed"],
        "needs_review": [k for k, v in targets.items() if v.get("status") != "confirmed"],
        "duplicate_creation_allowed": False,
        "migration_allowed": False,
        "next_required_before_migration": ["login/roles test harness", "IA PRO real tenant confirmation", "tenant-scoped data isolation tests"],
    }
