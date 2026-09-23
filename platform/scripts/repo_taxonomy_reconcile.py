#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OWNER = "Rafa-Innerchispa"
HERE = Path(__file__).resolve().parent
POLICY_PATH = HERE / "repository_taxonomy.json"
OUTPUT_PATH = Path("/home/rlopez/inneros/inneros_core/var/repo_sovereignty/repository-catalog.json")

ROLE_DEFAULTS = {
    "featured_system": ("active", "featured"),
    "active_product": ("active", "supporting"),
    "product_extension": ("experimental", "supporting"),
    "core_capability": ("active", "supporting"),
    "rd_hub": ("experimental", "supporting"),
    "experimental_probe": ("experimental", "evidence"),
    "validation_snapshot": ("submission_snapshot", "evidence"),
    "engineering_evidence": ("active", "evidence"),
    "legacy": ("legacy", "evidence"),
    "internal_operations": ("maintenance", "hidden"),
    "public_support": ("maintenance", "hidden"),
    "archive_candidate": ("maintenance", "hidden"),
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "1.0.0":
        raise ValueError("unsupported_taxonomy_schema_version")
    featured = data.get("featured_repositories") or []
    if len(featured) != 6 or len(set(featured)) != 6:
        raise ValueError("featured_repository_count_must_equal_6")
    return data


def _matches(name: str, patterns: list[str]) -> bool:
    lowered = name.lower()
    return any(p.lower() in lowered for p in patterns)


def classify_repo(repo: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    name = str(repo.get("name") or "").strip()
    full = str(repo.get("nameWithOwner") or repo.get("repository_full_name") or f"{OWNER}/{name}")
    is_private = bool(repo.get("isPrivate", repo.get("visibility") == "private"))
    default_branch = (
        ((repo.get("defaultBranchRef") or {}).get("name"))
        if isinstance(repo.get("defaultBranchRef"), dict)
        else repo.get("default_branch")
    ) or ""
    description = str(repo.get("description") or "")
    topics = list(repo.get("repositoryTopics") or repo.get("topics") or [])
    if topics and isinstance(topics[0], dict):
        topics = [str((x.get("name") or "")) for x in topics]
    text = " ".join([name, description, " ".join(topics)]).lower()

    overrides = policy.get("overrides") or {}
    override = overrides.get(full)
    if override:
        record = dict(override)
        record.update({
            "repository": full,
            "classification_source": "owner_policy",
            "classification_confidence": 1.0,
            "auto_classified": False,
        })
    elif full in set(policy.get("featured_repositories") or []):
        record = {
            "repository": full,
            "role": "featured_system",
            "lifecycle": "active",
            "portfolio_tier": "featured",
            "portfolio_visible": True,
            "profile_featured": True,
            "allow_auto_publication": False,
            "classification_source": "featured_policy",
            "classification_confidence": 1.0,
            "auto_classified": False,
        }
    else:
        rules = policy.get("rules") or {}
        role = None
        confidence = 0.0
        source = "guardian_rules_v1"
        parent = None
        successor = None

        if name.startswith("hyperloom-r9700-") and name != "hyperloom-r9700-experimental":
            role, confidence = "experimental_probe", 0.99
            parent = f"{OWNER}/hyperloom-r9700-experimental"
        elif _matches(name, rules.get("probe_name_patterns") or []):
            role, confidence = "experimental_probe", 0.92
        elif _matches(name, rules.get("snapshot_name_patterns") or []) or any(
            token in text for token in ("built for ", "hackathon", "devpost", "lablab")
        ):
            role, confidence = "validation_snapshot", 0.88
        elif _matches(name, rules.get("internal_name_patterns") or []) and is_private:
            role, confidence = "internal_operations", 0.93
        elif name in {"inneros-engineering-journal"}:
            role, confidence = "engineering_evidence", 0.98
        elif is_private:
            role, confidence = "internal_operations", 0.72
        elif not description and int(repo.get("size") or 0) == 0:
            role, confidence = "archive_candidate", 0.75
        elif name.startswith(("inneros-", "innerops-", "ralphiia-", "innerspark-")):
            role, confidence = "product_extension", 0.72
        else:
            role, confidence = "archive_candidate", 0.60

        lifecycle, tier = ROLE_DEFAULTS[role]
        record = {
            "repository": full,
            "role": role,
            "lifecycle": lifecycle,
            "portfolio_tier": tier,
            "portfolio_visible": tier != "hidden",
            "profile_featured": False,
            "allow_auto_publication": False,
            "classification_source": source,
            "classification_confidence": confidence,
            "auto_classified": True,
        }
        if parent:
            record["parent"] = parent
        if successor:
            record["successor"] = successor

    record.setdefault("portfolio_visible", record.get("portfolio_tier") != "hidden")
    record.setdefault("profile_featured", record.get("role") == "featured_system")
    record["allow_auto_publication"] = False
    record["github_visibility"] = "private" if is_private else "public"
    record["default_branch"] = default_branch
    record["description"] = description
    record["topics"] = topics
    return record


def validate_record(record: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    role = record.get("role")
    confidence = float(record.get("classification_confidence") or 0.0)

    if role == "experimental_probe" and not record.get("parent"):
        errors.append("experimental_probe_requires_parent")
    if role == "legacy" and not record.get("successor"):
        errors.append("legacy_requires_successor")
    if role == "featured_system" and record.get("default_branch") != "main":
        errors.append("featured_default_branch_not_main")
    if role == "featured_system" and not record.get("profile_featured"):
        errors.append("featured_requires_profile_featured")
    if record.get("allow_auto_publication") is not False:
        errors.append("taxonomy_must_never_auto_publish")

    if confidence < float(((policy.get("rules") or {}).get("confidence") or {}).get("provisional", 0.70)):
        warnings.append("classification_confidence_low")
        status = "NEEDS_REVIEW"
    elif errors:
        status = "BLOCKED"
    elif confidence < float(((policy.get("rules") or {}).get("confidence") or {}).get("auto_accept", 0.90)):
        warnings.append("classification_provisional")
        status = "PASS_WITH_WARNINGS"
    else:
        status = "PASS"

    if record.get("github_visibility") == "private" and record.get("portfolio_visible"):
        warnings.append("private_repo_marked_portfolio_visible")

    return {"status": status, "errors": errors, "warnings": warnings}


def list_github_repos(owner: str = OWNER) -> list[dict[str, Any]]:
    gh = shutil.which("gh")
    if not gh:
        raise RuntimeError("gh_unavailable")
    cmd = [
        gh, "repo", "list", owner, "--limit", "1000",
        "--json", "name,nameWithOwner,isPrivate,url,defaultBranchRef,description,repositoryTopics,updatedAt,pushedAt",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"github_list_failed:{proc.stderr[-500:]}")
    return json.loads(proc.stdout or "[]")


def build_catalog(repos: list[dict[str, Any]], policy: dict[str, Any]) -> dict[str, Any]:
    rows = []
    featured_seen = []
    for repo in repos:
        row = classify_repo(repo, policy)
        validation = validate_record(row, policy)
        row["validation"] = validation
        if row.get("role") == "featured_system":
            featured_seen.append(row["repository"])
        rows.append(row)

    global_errors = []
    expected = set(policy.get("featured_repositories") or [])
    actual = set(featured_seen)
    if actual != expected:
        global_errors.append({
            "code": "featured_set_mismatch",
            "expected": sorted(expected),
            "actual": sorted(actual),
        })

    counts = Counter(r["role"] for r in rows)
    status_counts = Counter(r["validation"]["status"] for r in rows)
    unclassified = [r["repository"] for r in rows if not r.get("role")]
    needs_review = [r["repository"] for r in rows if r["validation"]["status"] == "NEEDS_REVIEW"]
    blocked = [r["repository"] for r in rows if r["validation"]["status"] == "BLOCKED"]

    return {
        "schema_version": "1.0.0",
        "generated_at": now(),
        "owner": policy.get("owner", OWNER),
        "repository_count": len(rows),
        "category_counts": dict(sorted(counts.items())),
        "validation_counts": dict(sorted(status_counts.items())),
        "featured_repositories": sorted(actual),
        "unclassified": unclassified,
        "needs_review": needs_review,
        "blocked": blocked,
        "global_errors": global_errors,
        "publication_guard": "taxonomy_never_grants_public_visibility",
        "rows": sorted(rows, key=lambda r: r["repository"].lower()),
        "ok": not global_errors and not blocked and not unclassified,
    }


def main() -> int:
    policy = load_policy()
    repos = list_github_repos(policy.get("owner", OWNER))
    catalog = build_catalog(repos, policy)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(catalog, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "ok": catalog["ok"],
        "repository_count": catalog["repository_count"],
        "category_counts": catalog["category_counts"],
        "validation_counts": catalog["validation_counts"],
        "needs_review": catalog["needs_review"],
        "blocked": catalog["blocked"],
        "global_errors": catalog["global_errors"],
        "output": str(OUTPUT_PATH),
    }, sort_keys=True))
    return 0 if catalog["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
