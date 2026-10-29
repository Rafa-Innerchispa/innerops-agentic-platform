#!/usr/bin/env python3
"""Read-only fleet runtime SHA audit (no deploy, no service restart)."""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INTEL = os.getenv("INNEROS_INTEL_HOST", "rlopez@192.168.1.4")
DEFAULT_AMD = os.getenv("INNEROS_AMD_HOST", "rlopez@192.168.1.5")
GIT_ROOTS = (
    "~/inneros/inneros_core",
    "~/inneros/inneros_core/var/local_execution/worktrees/Rafa-Innerchispa__innerops-agentic-platform/platform",
)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _local_git_sha(path: Path) -> str | None:
    if not path.is_dir():
        return None
    proc = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def _ssh_git_sha(host: str, timeout: int = 8) -> dict:
    remote_cmd = (
        "for d in "
        + " ".join(GIT_ROOTS)
        + "; do expanded=${d/#\\~/\\$HOME}; if git -C \"$expanded\" rev-parse HEAD 2>/dev/null; then "
        "git -C \"$expanded\" log -1 --oneline; hostname; exit 0; fi; done; exit 1"
    )
    proc = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", host, remote_cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    sha = lines[0] if lines and len(lines[0]) == 40 else None
    return {
        "host": host,
        "ok": proc.returncode == 0 and bool(sha),
        "git_sha": sha,
        "log_line": lines[1] if len(lines) > 1 else None,
        "remote_hostname": lines[2] if len(lines) > 2 else None,
        "stderr": (proc.stderr or "")[-400:] or None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--task-id",
        default=os.getenv("INNEROS_OPS_TASK_ID", "ops_7039e9cc4f11"),
    )
    parser.add_argument("--expected-sha", default="", help="Optional merge/deploy target SHA")
    args = parser.parse_args()

    expected_sha = (args.expected_sha or "").strip()
    if not expected_sha:
        repo_root = ROOT.parent
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "origin/main"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if proc.returncode != 0:
            proc = subprocess.run(
                ["git", "-C", str(repo_root), "rev-parse", "main"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        if proc.returncode == 0:
            expected_sha = proc.stdout.strip()

    local_platform = ROOT
    local_core = ROOT.parent.parent if ROOT.name == "platform" else ROOT
    report: dict = {
        "ok": True,
        "generated_at": _utc(),
        "task_id": args.task_id,
        "auditor_host": socket.gethostname(),
        "expected_sha": expected_sha or None,
        "local": {
            "platform_sha": _local_git_sha(local_platform),
            "inneros_core_sha": _local_git_sha(local_core),
        },
        "fleet": {},
    }
    for label, host in (("intel", DEFAULT_INTEL), ("amd", DEFAULT_AMD)):
        row = _ssh_git_sha(host)
        report["fleet"][label] = row
        if not row.get("ok"):
            report["ok"] = False
    expected = expected_sha
    if expected:
        for node in report["fleet"].values():
            if node.get("git_sha") and node["git_sha"] != expected:
                node["matches_expected"] = False
                report["ok"] = False
            elif node.get("git_sha"):
                node["matches_expected"] = True

    out_path = ROOT.parent / "var" / "evidence" / f"{args.task_id}_runtime_deploy_audit.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({**report, "path": str(out_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
