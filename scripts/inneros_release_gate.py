#!/usr/bin/env python3
"""Offline fail-closed release metadata check, never a live host certification.

No network, service, git, deployment, tag, or Release mutation is performed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ATTESTATION = ROOT / "docs" / "INNEROS_RELEASE_ATTESTATION.json"
LKG = ROOT / "docs" / "INNEROS_LAST_KNOWN_GOOD.json"
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
SEMVER = re.compile(r"v\d+\.\d+\.\d+\Z")
NODES = ("amd", "intel")


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp.astimezone(timezone.utc) if stamp.tzinfo else None
    except ValueError:
        return None


def _passed(value: object) -> bool:
    return type(value) is int and value == 0


def evaluate(candidate_sha: str, attestation: dict, lkg: dict,
             now: datetime | None = None) -> dict:
    """Pure metadata gate. Never implies a living process was independently seen."""
    if not isinstance(candidate_sha, str) or not HEX40.fullmatch(candidate_sha):
        raise ValueError("candidate_must_be_full_lowercase_git_sha")
    if not isinstance(attestation, dict) or not isinstance(lkg, dict):
        raise ValueError("invalid_manifest_type")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now_requires_timezone")
    now = now.astimezone(timezone.utc)
    blockers: list[str] = []
    hosts = attestation.get("hosts")
    hosts = hosts if isinstance(hosts, dict) else {}
    if attestation.get("schema") != "inneros-runtime-host-attestation-v1":
        blockers.append("invalid_attestation_schema")
    paths: list[str] = []
    for node in NODES:
        data = hosts.get(node)
        data = data if isinstance(data, dict) else {}
        if data.get("verified") is not True:
            blockers.append(node + ":not_attested")
        if data.get("runtime_git_sha") != candidate_sha:
            blockers.append(node + ":runtime_sha_mismatch")
        path = data.get("evidence_path")
        if not isinstance(path, str) or not path.strip():
            blockers.append(node + ":receipt_missing")
        else:
            paths.append(path)
        imported_sha = data.get("runtime_import_sha256")
        if not isinstance(imported_sha, str) or not HEX64.fullmatch(imported_sha):
            blockers.append(node + ":import_hash_missing")
        pid = data.get("runtime_pid")
        if type(pid) is not int or pid <= 0:
            blockers.append(node + ":pid_missing")
        if not _passed(data.get("tests_exit_code")):
            blockers.append(node + ":tests_not_passed")
        if not _passed(data.get("smoke_exit_code")):
            blockers.append(node + ":smoke_not_passed")
        if not isinstance(data.get("rollback_snapshot"), str) or not data["rollback_snapshot"].strip():
            blockers.append(node + ":rollback_snapshot_missing")
        verified_at = _timestamp(data.get("verified_at_utc"))
        if verified_at is None or abs(now - verified_at) > timedelta(hours=24):
            blockers.append(node + ":receipt_stale")
    if len(paths) == 2 and paths[0] == paths[1]:
        blockers.append("host_receipts_must_be_distinct")
    if lkg.get("schema") != "inneros-last-known-good-v1":
        blockers.append("invalid_lkg_schema")
    elif lkg.get("status") == "UNSET":
        pass  # First release does not have a predecessor: never invent one.
    elif lkg.get("status") == "CERTIFIED":
        if not HEX40.fullmatch(str(lkg.get("git_sha") or "")):
            blockers.append("invalid_lkg_git_sha")
        if not SEMVER.fullmatch(str(lkg.get("release_tag") or "")):
            blockers.append("invalid_lkg_release_tag")
        lkg_hosts = lkg.get("hosts")
        if not isinstance(lkg_hosts, dict) or any(
            not isinstance(lkg_hosts.get(n), dict) or
            not lkg_hosts[n].get("rollback_snapshot") for n in NODES
        ):
            blockers.append("lkg_missing_node_rollback")
    else:
        blockers.append("invalid_lkg_status")
    return {
        "schema": "inneros-release-preflight-v1",
        "candidate_sha": candidate_sha,
        "status": "HOST_METADATA_PRESENT_RECHECK_REQUIRED" if not blockers else "BLOCKED",
        "host_metadata_complete": not blockers,
        "blockers": blockers,
        "lkg_status": lkg.get("status"),
        "production_runtime_verified_by_this_check": False,
        "github_release_authorized_by_this_check": False,
        "next_gate": "Independent AMD+Intel live process and import hashes, smoke, Temporal/Mongo terminal, rollback review",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--candidate-sha", required=True)
    p.add_argument("--attestation", type=Path, default=ATTESTATION)
    p.add_argument("--lkg", type=Path, default=LKG)
    p.add_argument("--require-host-metadata", action="store_true")
    args = p.parse_args()
    try:
        att = json.loads(args.attestation.read_text(encoding="utf-8"))
        lkg = json.loads(args.lkg.read_text(encoding="utf-8"))
        report = evaluate(args.candidate_sha, att, lkg)
    except (OSError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": type(exc).__name__,
                          "github_release_authorized_by_this_check": False}))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 2 if args.require_host_metadata and not report["host_metadata_complete"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
