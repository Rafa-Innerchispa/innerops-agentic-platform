#!/usr/bin/env python3
"""Read-only inventory of the dirty AMD checkout before any reconciliation."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

AMD_HOSTS = tuple(dict.fromkeys(filter(None, (
    os.getenv("RALFIA_AMD_HOST", "100.72.153.124"),
    os.getenv("RALFIA_AMD_LAN_HOST", "192.168.1.5"),
))))
REMOTE_REPO = os.getenv("INNEROS_LIVE_REPO", "/home/rlopez/inneros/inneros_core")
CODE_EXTENSIONS = {
    ".py", ".sh", ".js", ".ts", ".tsx", ".json", ".yaml", ".yml",
    ".toml", ".md", ".sql", ".html", ".css", ".env", ".service",
}


def ssh(host: str, command: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=5",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            f"rlopez@{host}",
            f"cd {REMOTE_REPO} && {command}",
        ],
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def first_reachable() -> tuple[str, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    for host in AMD_HOSTS:
        result = ssh(host, "git rev-parse --is-inside-work-tree")
        ok = result.returncode == 0 and result.stdout.strip() == "true"
        attempts.append({"host": host, "ok": ok, "error": result.stderr.strip()[:200] or None})
        if ok:
            return host, attempts
    raise SystemExit(json.dumps({"ok": False, "attempts": attempts}, indent=2))


def remote_text(host: str, command: str, timeout: int = 30) -> str:
    result = ssh(host, command, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"remote command failed: {command}: {result.stderr.strip()[:300]}")
    return result.stdout


def parse_status(raw: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in raw.splitlines():
        if len(line) < 4:
            continue
        code = line[:2]
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        rows.append({"code": code, "path": path})
    return rows


def main() -> None:
    host, attempts = first_reachable()
    branch = remote_text(host, "git branch --show-current").strip()
    head = remote_text(host, "git rev-parse HEAD").strip()
    status_raw = remote_text(host, "git status --porcelain=v1 -uall", timeout=60)
    rows = parse_status(status_raw)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    evidence_dir = Path(".canary") / "amd-preservation" / stamp
    evidence_dir.mkdir(parents=True, exist_ok=False)
    status_path = evidence_dir / "git-status-porcelain.txt"
    status_path.write_text(status_raw, encoding="utf-8")

    code_counts = Counter(row["code"] for row in rows)
    root_counts = Counter(row["path"].split("/", 1)[0] for row in rows)
    tracked = [row for row in rows if row["code"] != "??"]
    untracked = [row for row in rows if row["code"] == "??"]
    code_like = [
        row for row in rows
        if Path(row["path"]).suffix.lower() in CODE_EXTENSIONS
        or row["path"].startswith(("platform/", "scripts/", "docs/", "deploy/", "infra/"))
    ]
    critical = [
        row for row in code_like
        if row["path"].startswith((
            "platform/inneros_core_runtime/",
            "platform/tests/",
            "scripts/",
            "deploy/",
            "infra/",
        ))
    ]

    report = {
        "ok": True,
        "mode": "read_only_amd_preservation_audit",
        "production_mutated": False,
        "host": host,
        "attempts": attempts,
        "repo": REMOTE_REPO,
        "branch": branch,
        "head": head,
        "status_count": len(rows),
        "tracked_change_count": len(tracked),
        "untracked_count": len(untracked),
        "code_like_change_count": len(code_like),
        "critical_code_change_count": len(critical),
        "status_codes": dict(sorted(code_counts.items())),
        "top_level_paths": dict(root_counts.most_common()),
        "critical_code_paths": critical[:100],
        "critical_code_paths_truncated": len(critical) > 100,
        "status_sha256": hashlib.sha256(status_raw.encode("utf-8")).hexdigest(),
        "evidence_file": str(status_path.resolve()),
        "next_gate": "preserve tracked and untracked AMD work before checkout, reset, merge, rsync, or deployment",
    }
    (evidence_dir / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
