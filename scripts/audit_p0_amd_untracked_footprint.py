#!/usr/bin/env python3
"""Read-only AMD untracked-file size and path classification."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
import os
from pathlib import PurePosixPath
import subprocess
from typing import Any

AMD_HOSTS = tuple(dict.fromkeys(filter(None, (
    os.getenv("RALFIA_AMD_HOST", "100.72.153.124"),
    os.getenv("RALFIA_AMD_LAN_HOST", "192.168.1.5"),
))))
REMOTE_REPO = os.getenv("INNEROS_LIVE_REPO", "/home/rlopez/inneros/inneros_core")


def ssh_bytes(host: str, command: str, timeout: int = 120) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
            f"rlopez@{host}", f"cd {REMOTE_REPO} && {command}",
        ],
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def first_reachable() -> tuple[str, list[dict[str, Any]]]:
    attempts = []
    for host in AMD_HOSTS:
        result = ssh_bytes(host, "git rev-parse --is-inside-work-tree", timeout=15)
        ok = result.returncode == 0 and result.stdout.strip() == b"true"
        attempts.append({"host": host, "ok": ok, "error": result.stderr.decode(errors="replace").strip()[:200] or None})
        if ok:
            return host, attempts
    raise SystemExit(json.dumps({"ok": False, "attempts": attempts}, indent=2))


def human_bytes(value: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.2f} {unit}"
        amount /= 1024
    return f"{value} B"


def main() -> None:
    host, attempts = first_reachable()
    command = (
        "git ls-files --others --exclude-standard -z | "
        "xargs -0 -r stat --printf='%s\\t%n\\0'"
    )
    result = ssh_bytes(host, command, timeout=180)
    if result.returncode != 0:
        raise SystemExit(json.dumps({
            "ok": False,
            "host": host,
            "error": result.stderr.decode(errors="replace")[:500],
        }, indent=2))

    rows: list[tuple[str, int]] = []
    for item in result.stdout.split(b"\0"):
        if not item or b"\t" not in item:
            continue
        size_raw, path_raw = item.split(b"\t", 1)
        try:
            size = int(size_raw)
        except ValueError:
            continue
        path = path_raw.decode("utf-8", errors="surrogateescape")
        rows.append((path, size))

    by_root_count: Counter[str] = Counter()
    by_root_bytes: defaultdict[str, int] = defaultdict(int)
    by_prefix_count: Counter[str] = Counter()
    by_prefix_bytes: defaultdict[str, int] = defaultdict(int)
    suffix_count: Counter[str] = Counter()
    suffix_bytes: defaultdict[str, int] = defaultdict(int)

    for path, size in rows:
        parts = PurePosixPath(path).parts
        root = parts[0] if parts else "<root>"
        prefix = "/".join(parts[:2]) if len(parts) >= 2 else root
        suffix = PurePosixPath(path).suffix.lower() or "<none>"
        by_root_count[root] += 1
        by_root_bytes[root] += size
        by_prefix_count[prefix] += 1
        by_prefix_bytes[prefix] += size
        suffix_count[suffix] += 1
        suffix_bytes[suffix] += size

    largest = sorted(rows, key=lambda row: row[1], reverse=True)[:50]
    top_prefixes = sorted(
        by_prefix_count,
        key=lambda key: (by_prefix_bytes[key], by_prefix_count[key]),
        reverse=True,
    )[:50]
    top_suffixes = sorted(
        suffix_count,
        key=lambda key: (suffix_bytes[key], suffix_count[key]),
        reverse=True,
    )[:30]

    total_bytes = sum(size for _, size in rows)
    report = {
        "ok": True,
        "mode": "read_only_amd_untracked_footprint",
        "production_mutated": False,
        "host": host,
        "attempts": attempts,
        "untracked_file_count": len(rows),
        "untracked_total_bytes": total_bytes,
        "untracked_total_human": human_bytes(total_bytes),
        "top_level": [
            {
                "path": key,
                "count": by_root_count[key],
                "bytes": by_root_bytes[key],
                "human": human_bytes(by_root_bytes[key]),
            }
            for key in sorted(by_root_count, key=lambda item: by_root_bytes[item], reverse=True)
        ],
        "top_prefixes": [
            {
                "path": key,
                "count": by_prefix_count[key],
                "bytes": by_prefix_bytes[key],
                "human": human_bytes(by_prefix_bytes[key]),
            }
            for key in top_prefixes
        ],
        "top_suffixes": [
            {
                "suffix": key,
                "count": suffix_count[key],
                "bytes": suffix_bytes[key],
                "human": human_bytes(suffix_bytes[key]),
            }
            for key in top_suffixes
        ],
        "largest_files": [
            {"path": path, "bytes": size, "human": human_bytes(size)}
            for path, size in largest
        ],
        "next_gate": "choose content-preserving archive scope; no reset, clean, checkout, or rsync",
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
