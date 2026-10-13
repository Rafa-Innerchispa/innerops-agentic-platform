#!/usr/bin/env python3
"""Bounded local GitHub release executor: preview, backup, stage, verify, rollback.

Run on a trusted self-hosted AMD/Intel runner. Never fetch or execute code from
untrusted pull requests. The workflow pins a reviewed main SHA and does not
permit arbitrary shell commands, arbitrary destination paths, or destructive bulk sync.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path("/home/rlopez/inneros/inneros_core/platform/inneros_core_runtime")
BACKUP_ROOT = Path("/home/rlopez/inneros/inneros_core/var/release-backups")
FILES = (
    "capability_gateway.py",
    "capability_gateway_peer.py",
    "agents/ag41_peer_ops_executor.py",
    "dev_swarm_scheduler.py",
    "temporal_bounded_executor.py",
    "governed_model_writes.py",
)
SERVICE = "ralfia-mcp.service"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(REPO_ROOT), *args], text=True).strip()


def fail(message: str) -> None:
    raise RuntimeError(message)


def path_within(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sha", required=True)
    p.add_argument("--mode", choices=("plan", "apply"), default="plan")
    p.add_argument("--restart", action="store_true")
    args = p.parse_args()

    if not (len(args.sha) == 40 and all(c in "0123456789abcdef" for c in args.sha)):
        fail("full_lowercase_sha_required")
    head = git("rev-parse", "HEAD")
    if head != args.sha:
        fail("checkout_sha_mismatch")
    if git("status", "--porcelain", "--untracked-files=no"):
        fail("dirty_candidate_checkout")
    if subprocess.run(
        ["git", "-C", str(REPO_ROOT), "merge-base", "--is-ancestor", head, "origin/main"],
        check=False, capture_output=True,
    ).returncode:
        fail("candidate_not_on_origin_main")
    if args.mode == "apply" and os.environ.get("INNEROS_APPROVED_RELEASE") != args.sha:
        fail("approved_release_sha_not_pinned")
    if args.mode == "apply" and os.environ.get("RUNNER_ENVIRONMENT") != "self-hosted":
        fail("self_hosted_runner_required")

    manifest = []
    for rel in FILES:
        src = REPO_ROOT / "platform" / "inneros_core_runtime" / rel
        dest = RUNTIME / rel
        if not src.is_file() or not path_within(dest, RUNTIME):
            fail("unapproved_source_or_destination: " + rel)
        compile(src.read_bytes(), str(src), "exec")
        manifest.append({"file": rel, "candidate_sha256": sha256(src),
                         "current_sha256": sha256(dest) if dest.is_file() else None})
    output = {"mode": args.mode, "candidate_sha": head,
              "target": str(RUNTIME), "files": manifest,
              "production_mutated": False}
    if args.mode == "plan":
        print(json.dumps(output, sort_keys=True))
        return 0

    if not RUNTIME.is_dir():
        fail("runtime_target_missing")
    if args.restart and not shutil.which("systemctl"):
        fail("systemctl_missing")
    snapshot = BACKUP_ROOT / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + head[:12])
    snapshot.mkdir(parents=True, exist_ok=False)
    existing = {}
    changed = []
    try:
        # Backup all existing destinations before the first production write.
        for item in manifest:
            rel = item["file"]
            dest = RUNTIME / rel
            existing[rel] = dest.is_file()
            if dest.exists():
                backup = snapshot / rel
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, backup)
        for item in manifest:
            rel = item["file"]
            src = REPO_ROOT / "platform" / "inneros_core_runtime" / rel
            dest = RUNTIME / rel
            tmp = dest.with_name(dest.name + ".release-staging")
            tmp.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, tmp)
            if sha256(tmp) != item["candidate_sha256"]:
                fail("staged_hash_mismatch")
            os.replace(tmp, dest)
            changed.append(rel)
        for item in manifest:
            if sha256(RUNTIME / item["file"]) != item["candidate_sha256"]:
                fail("deployed_hash_mismatch")
        if args.restart:
            subprocess.run(["systemctl", "--user", "restart", SERVICE], check=True, timeout=40)
            subprocess.run(["systemctl", "--user", "is-active", "--quiet", SERVICE], check=True, timeout=20)
        output.update({"production_mutated": True, "snapshot": str(snapshot),
                       "restarted": bool(args.restart), "rollback_performed": False})
        print(json.dumps(output, sort_keys=True))
        return 0
    except Exception:
        for rel in reversed(changed):
            dest = RUNTIME / rel
            if existing.get(rel):
                shutil.copy2(snapshot / rel, dest)
            else:
                dest.unlink(missing_ok=True)
        if args.restart:
            subprocess.run(["systemctl", "--user", "restart", SERVICE], check=False, timeout=40)
        print(json.dumps({"ok": False, "rollback_performed": True,
                          "snapshot": str(snapshot)}, sort_keys=True), file=sys.stderr)
        raise


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)[:250]}), file=sys.stderr)
        raise SystemExit(1)
