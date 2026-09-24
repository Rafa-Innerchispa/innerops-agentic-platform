#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_ROOT = Path("/home/rlopez/inneros/inneros_core/var/repo_sovereignty")
CATALOG_PATH = STATE_ROOT / "repository-catalog.json"
DISCOVERY_PATH = STATE_ROOT / "account-discovery.json"
OUTPUT_PATH = STATE_ROOT / "guardian-health.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}_not_object")
    return data


def evaluate(catalog: dict[str, Any], discovery: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []

    needs_review = list(catalog.get("needs_review") or [])
    blocked = list(catalog.get("blocked") or [])
    unclassified = list(catalog.get("unclassified") or [])

    for repo in needs_review:
        issues.append({"kind": "needs_review", "repo": repo})
    for repo in blocked:
        issues.append({"kind": "blocked", "repo": repo})
    for repo in unclassified:
        issues.append({"kind": "unclassified", "repo": repo})

    visibility_mismatches = []
    mirror_failures = []
    for row in discovery.get("rows") or []:
        repo = str(row.get("repo") or "")
        github_visibility = row.get("github_visibility")
        gitlab_visibility = row.get("gitlab_visibility")
        if github_visibility and gitlab_visibility and github_visibility != gitlab_visibility:
            item = {
                "kind": "visibility_mismatch",
                "repo": repo,
                "github_visibility": github_visibility,
                "gitlab_visibility": gitlab_visibility,
            }
            visibility_mismatches.append(item)
            issues.append(item)

        if row.get("mirror_fsck_ok") is not True:
            item = {"kind": "mirror_fsck_failed", "repo": repo, "mirror": row.get("mirror")}
            mirror_failures.append(item)
            issues.append(item)

    if discovery.get("ok") is not True:
        for failure in discovery.get("failures") or []:
            issues.append({
                "kind": "account_discovery_failure",
                "repo": failure.get("repo"),
                "stage": failure.get("stage"),
            })

    return {
        "ok": not issues,
        "checked_at": now(),
        "repository_count": int(catalog.get("repository_count") or discovery.get("count") or 0),
        "counts": {
            "needs_review": len(needs_review),
            "blocked": len(blocked),
            "unclassified": len(unclassified),
            "visibility_mismatches": len(visibility_mismatches),
            "mirror_fsck_failures": len(mirror_failures),
            "account_discovery_failures": len(discovery.get("failures") or []),
        },
        "issues": issues,
        "sources": {
            "repository_catalog_generated_at": catalog.get("generated_at"),
            "account_discovery_timestamp": discovery.get("timestamp"),
        },
        "scope": "repo_sovereignty_only",
        "contributorops_touched": False,
    }


def main() -> int:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        catalog = load_json(CATALOG_PATH)
        discovery = load_json(DISCOVERY_PATH)
        payload = evaluate(catalog, discovery)
    except Exception as exc:
        payload = {
            "ok": False,
            "checked_at": now(),
            "repository_count": 0,
            "counts": {
                "needs_review": 0,
                "blocked": 0,
                "unclassified": 0,
                "visibility_mismatches": 0,
                "mirror_fsck_failures": 0,
                "account_discovery_failures": 0,
            },
            "issues": [{"kind": "health_check_input_error", "detail": str(exc)}],
            "scope": "repo_sovereignty_only",
            "contributorops_touched": False,
        }

    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
