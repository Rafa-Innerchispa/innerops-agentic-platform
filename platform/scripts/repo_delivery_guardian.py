#!/usr/bin/env python3
"""InnerOS universal delivery evidence auditor for every GitHub project.

Read-only with respect to GitHub, GitLab, worktrees and servers. Unlike mirror
services, this tool NEVER changes repo visibility, merges, creates branches,
pushes code, creates a release or deploys. Detailed results stay locally with
private filesystem permissions. Stdout contains only aggregate counts.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any
from urllib.parse import quote

OWNER = "Rafa-Innerchispa"
ROOT = Path("/home/rlopez/inneros/inneros_core/var/repo_sovereignty")
CATALOG = ROOT / "repository-catalog.json"
DISCOVERY = ROOT / "account-discovery.json"
GITLAB_SYNC = ROOT / "gitlab-sync.json"
RECEIPTS = ROOT / "delivery-runtime-receipts.json"
OUTPUT = ROOT / "universal-delivery-health.json"
REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
FINAL = {"passed", "success"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def stamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        v = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return v.astimezone(timezone.utc) if v.tzinfo else None
    except ValueError:
        return None


def recent(source: dict, keys: tuple[str, ...], now: datetime, hours: int = 24) -> bool:
    for key in keys:
        value = stamp(source.get(key))
        if value is not None:
            return timedelta(0) <= now - value <= timedelta(hours=hours)
    return False


def read_state(path: Path) -> dict:
    if not path.exists():
        return {"_missing": True}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"_invalid": True}
        return data
    except (OSError, ValueError):
        return {"_invalid": True}


def _run(argv: list[str], timeout: int = 45) -> tuple[Any | None, str | None]:
    """Never reveal stderr: gh/glab helpers may carry authentication details."""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None, "command_unavailable_or_timeout"
    if proc.returncode:
        return None, "command_failed_" + str(proc.returncode)
    try:
        return json.loads(proc.stdout), None
    except json.JSONDecodeError:
        return None, "invalid_json"


def inventory(gh: str, owner: str) -> list[dict]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner):
        raise ValueError("invalid_owner")
    data, error = _run([gh, "repo", "list", owner, "--limit", "1000",
                        "--json", "nameWithOwner,isPrivate,isArchived,defaultBranchRef,url"],
                       timeout=120)
    if error or not isinstance(data, list) or not data:
        raise RuntimeError("github_portfolio_unavailable")
    normalized = {}
    for row in data:
        full = str(row.get("nameWithOwner") or "")
        if not REPO_RE.fullmatch(full) or full.split("/", 1)[0] != owner:
            raise RuntimeError("invalid_github_repo_identifier")
        if full in normalized:
            raise RuntimeError("duplicate_github_repository")
        normalized[full] = row
    if len(data) >= 1000:
        raise RuntimeError("github_inventory_limit_reached")
    return [normalized[key] for key in sorted(normalized)]


def _api(gh: str, endpoint: str) -> tuple[Any | None, str | None]:
    return _run([gh, "api", endpoint], timeout=45)


def inspect(gh: str, item: dict) -> dict:
    full = str(item["nameWithOwner"])
    if not REPO_RE.fullmatch(full):
        raise ValueError("invalid_repo")
    metadata, meta_error = _api(gh, "repos/" + full)
    if not isinstance(metadata, dict):
        return {"source_ok": False, "error": meta_error or "invalid_metadata"}
    branch = str(metadata.get("default_branch") or "")
    branch_info, branch_error = _api(gh, "repos/" + full + "/branches/" + quote(branch, safe=""))
    releases, release_error = _api(gh, "repos/" + full + "/releases?per_page=5")
    runs, ci_error = _api(gh, "repos/" + full + "/actions/runs?per_page=30&branch=" + quote(branch, safe=""))
    if not isinstance(branch_info, dict):
        branch_info = {}
    if not isinstance(releases, list):
        releases = []
    if not isinstance(runs, dict):
        runs = {}
    head = (branch_info.get("commit") or {}).get("sha")
    matching = [
        w for w in (runs.get("workflow_runs") or [])
        if w.get("head_sha") == head and w.get("head_branch") == branch
        and w.get("status") == "completed" and w.get("conclusion") == "success"
    ] if SHA_RE.fullmatch(str(head or "")) else []
    official = [
        release for release in releases
        if not release.get("draft") and release.get("published_at")
        and str(release.get("tag_name") or "")
    ]
    return {
        "source_ok": not (meta_error or branch_error or release_error or ci_error),
        "source_errors": list(filter(None, [meta_error, branch_error, release_error, ci_error])),
        "default_branch": branch, "head_sha": head,
        "protected": branch_info.get("protected") is True if not branch_error else None,
        "issues_enabled": metadata.get("has_issues"),
        "archived": metadata.get("archived"),
        "private": metadata.get("private"),
        "ci_success_on_head": bool(matching) if not ci_error else None,
        "last_successful_ci_run_id": matching[0]["id"] if matching else None,
        "release_exists": bool(official) if not release_error else None,
        "latest_release": official[0].get("tag_name") if official else None,
    }


def _receipt_verified(repo: str, sha: str, evidence: dict,
                      now: datetime) -> bool:
    """Strict enough to reject agent claims, ACKs and stale/unpinned receipts."""
    if evidence.get("repo") != repo or evidence.get("runtime_git_sha") != sha:
        return False
    if evidence.get("verified") is not True or evidence.get("independent_verifier") is not True:
        return False
    h = evidence.get("runtime_import_sha256")
    if not isinstance(h, str) or not HASH_RE.fullmatch(h):
        return False
    if not isinstance(evidence.get("rollback_snapshot"), str) or not evidence["rollback_snapshot"]:
        return False
    if any(type(evidence.get(k)) is not int or evidence[k] != 0 for k in
           ("tests_exit_code", "smoke_exit_code")):
        return False
    if type(evidence.get("runtime_pid")) is not int or evidence["runtime_pid"] <= 0:
        return False
    if not isinstance(evidence.get("evidence_path"), str) or not evidence["evidence_path"]:
        return False
    return recent(evidence, ("verified_at_utc",), now, hours=24)


def evaluate(rows: list[dict], github: dict[str, dict], catalog: dict,
             discovery: dict, gitlab: dict, receipts: dict,
             now: datetime | None = None) -> dict:
    now = now or utcnow()
    if now.tzinfo is None:
        raise ValueError("now_requires_timezone")
    if not rows or any(not REPO_RE.fullmatch(str(r.get("nameWithOwner") or "")) for r in rows):
        raise ValueError("invalid_or_empty_github_inventory")
    keys = [r["nameWithOwner"] for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate_repository")
    taxonomy = {r.get("repository"): r for r in catalog.get("rows", []) if isinstance(r, dict)}
    mirror = {r.get("repo"): r for r in discovery.get("rows", []) if isinstance(r, dict)}
    glsync = {r.get("github"): r for r in gitlab.get("rows", []) if isinstance(r, dict)}
    host_receipts = receipts.get("repositories") if isinstance(receipts, dict) else {}
    host_receipts = host_receipts if isinstance(host_receipts, dict) else {}
    source_fresh = {
        "taxonomy": recent(catalog, ("generated_at",), now),
        "github_gitlab_discovery": recent(discovery, ("timestamp",), now),
        "gitlab_sync": recent(gitlab, ("timestamp",), now),
    }
    projects = []
    counts = {"governed": 0, "needs_attention": 0,
              "source_unverified": 0, "production_certified": 0}
    for row in rows:
        name = row["nameWithOwner"]
        t = taxonomy.get(name) or {}
        d = mirror.get(name) or {}
        g = glsync.get(name) or {}
        gh = github.get(name) or {}
        gaps = []
        if not t or not source_fresh["taxonomy"]:
            gaps.append("taxonomy_missing_or_stale")
        if not d or not source_fresh["github_gitlab_discovery"]:
            gaps.append("mirror_discovery_missing_or_stale")
        elif d.get("mirror_fsck_ok") is not True:
            gaps.append("backup_mirror_unverified")
        if not g or not source_fresh["gitlab_sync"]:
            gaps.append("gitlab_sync_missing_or_stale")
        elif g.get("branches_ok") is not True or g.get("tags_ok") is not True:
            gaps.append("gitlab_refs_or_tags_unverified")
        if gh.get("source_ok") is not True:
            gaps.append("github_api_unverified")
        if not gh.get("head_sha") or not SHA_RE.fullmatch(str(gh["head_sha"])):
            gaps.append("default_branch_sha_unknown")
        if gh.get("protected") is not True:
            gaps.append("default_branch_unprotected_or_unknown")
        if gh.get("issues_enabled") is not True:
            gaps.append("github_issues_off_or_unknown")
        if gh.get("ci_success_on_head") is not True:
            gaps.append("ci_not_proven_for_default_sha")
        if gh.get("release_exists") is not True:
            gaps.append("official_release_missing_or_unknown")
        if bool(row.get("isPrivate")) != gh.get("private"):
            gaps.append("visibility_not_verified")
        release_applicable = t.get("lifecycle") in {"active", "maintenance"}
        if not release_applicable and "official_release_missing_or_unknown" in gaps:
            # Preserve archived/experimental histories without forcing deployment.
            gaps.remove("official_release_missing_or_unknown")
        nodes = host_receipts.get(name) or {}
        receipt_status = {}
        for node, evidence in (nodes.items() if isinstance(nodes, dict) else []):
            receipt_status[node] = _receipt_verified(
                name, str(gh.get("head_sha") or ""), evidence, now
            ) if isinstance(evidence, dict) else False
        prod_status = "NO_CERTIFICADO"
        if release_applicable and nodes and all(receipt_status.values()):
            prod_status = "HOST_EVIDENCE_RECORDED_RECHECK_REQUIRED"
        elif not release_applicable:
            prod_status = "NO_APLICA_SIN_DEPLOY_DECLARADO"
        governed = not gaps
        if governed:
            counts["governed"] += 1
        else:
            counts["needs_attention"] += 1
        if not gh.get("source_ok"):
            counts["source_unverified"] += 1
        # Never increment production_certified based only on metadata.
        projects.append({
            "repo": name, "role": t.get("role") or "unknown",
            "lifecycle": t.get("lifecycle") or "unknown",
            "default_branch": gh.get("default_branch") or "",
            "default_sha": gh.get("head_sha"),
            "visibility": "private" if row.get("isPrivate") else "public",
            "governance_state": "RECORDED_GATES_ONLY" if governed else "NEEDS_ATTENTION",
            "gaps": sorted(set(gaps)),
            "prod_status": prod_status,
            "host_receipt_status": receipt_status,
            "release_tag": gh.get("latest_release"),
            "github_ci_run_id": gh.get("last_successful_ci_run_id"),
        })
    return {
        "schema": "inneros-universal-delivery-audit-v1",
        "as_of_utc": now.isoformat(), "observed_repos": len(rows),
        "coverage_complete": len(github) == len(rows) and all(gh.get("source_ok") for gh in github.values()),
        "source_fresh": source_fresh, "counts": counts,
        "projects": projects, "no_branch_merged_or_deleted": True,
        "no_production_changes": True,
        "private_details_not_for_public_ci_artifacts": True,
    }


def save_private(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd, temporary = tempfile.mkstemp(prefix=".delivery-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            os.fchmod(out.fileno(), 0o600)
            json.dump(data, out, indent=2, sort_keys=True)
            out.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", default=OWNER)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()
    gh = shutil.which("gh")
    if not gh:
        print(json.dumps({"ok": False, "error": "gh_cli_unavailable"}))
        return 2
    try:
        rows = inventory(gh, args.owner)
    except (RuntimeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    observed = {}
    with ThreadPoolExecutor(max_workers=max(1, min(args.max_workers, 4))) as pool:
        jobs = {pool.submit(inspect, gh, row): row["nameWithOwner"] for row in rows}
        for job in as_completed(jobs):
            name = jobs[job]
            try:
                observed[name] = job.result()
            except Exception:
                observed[name] = {"source_ok": False, "error": "repo_probe_failed"}
    report = evaluate(rows, observed, read_state(CATALOG), read_state(DISCOVERY),
                      read_state(GITLAB_SYNC), read_state(RECEIPTS))
    if not args.no_save:
        save_private(args.output, report)
    # Keep private repo names, paths and host details out of stdout and GitHub CI.
    print(json.dumps({
        "ok": report["coverage_complete"] and report["counts"]["needs_attention"] == 0,
        "observed_repos": report["observed_repos"],
        "coverage_complete": report["coverage_complete"],
        "source_fresh": report["source_fresh"],
        "counts": report["counts"],
        "private_report_local": not args.no_save,
    }, sort_keys=True))
    return 0 if report["coverage_complete"] and report["counts"]["needs_attention"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
