#!/usr/bin/env python3
"""Preserve AMD Git drift and non-regenerable untracked files without remote mutation."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
from typing import Any

EXPECTED_ACK = "I_UNDERSTAND_READ_ONLY_AMD_SNAPSHOT"
if os.environ.get("INNEROS_P0_AMD_SNAPSHOT_ACK") != EXPECTED_ACK:
    raise SystemExit(f"REFUSED: set INNEROS_P0_AMD_SNAPSHOT_ACK={EXPECTED_ACK}")

AMD_HOSTS = tuple(dict.fromkeys(filter(None, (
    os.getenv("RALFIA_AMD_HOST", "100.72.153.124"),
    os.getenv("RALFIA_AMD_LAN_HOST", "192.168.1.5"),
))))
REMOTE_REPO = os.getenv("INNEROS_LIVE_REPO", "/home/rlopez/inneros/inneros_core")
EXCLUDED_REGENERABLE_PREFIXES = ("tools/go/", "var/local_models/")


def ssh(host: str, command: str, *, binary: bool = False, timeout: int = 300) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        [
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
            f"rlopez@{host}", f"cd {REMOTE_REPO} && {command}",
        ],
        text=not binary,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def first_reachable() -> tuple[str, list[dict[str, Any]]]:
    attempts = []
    for host in AMD_HOSTS:
        result = ssh(host, "git rev-parse --is-inside-work-tree", timeout=15)
        ok = result.returncode == 0 and result.stdout.strip() == "true"
        attempts.append({"host": host, "ok": ok, "error": result.stderr.strip()[:200] or None})
        if ok:
            return host, attempts
    raise SystemExit(json.dumps({"ok": False, "attempts": attempts}, indent=2))


def text_command(host: str, command: str, timeout: int = 120) -> str:
    result = ssh(host, command, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"remote command failed: {command}: {result.stderr.strip()[:500]}")
    return result.stdout


def bytes_command(host: str, command: str, timeout: int = 600) -> bytes:
    result = ssh(host, command, binary=True, timeout=timeout)
    if result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"remote binary command failed: {error}")
    return result.stdout


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    host, attempts = first_reachable()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path(".canary") / "amd-rescue" / stamp
    output_dir.mkdir(parents=True, exist_ok=False)

    branch = text_command(host, "git branch --show-current").strip()
    head = text_command(host, "git rev-parse HEAD").strip()
    status = text_command(host, "git status --porcelain=v1 -uall", timeout=120)
    log = text_command(host, "git log -20 --oneline --decorate --no-color")
    tracked_patch = text_command(host, "git diff --binary HEAD", timeout=180)
    staged_patch = text_command(host, "git diff --cached --binary", timeout=180)
    model_manifest = text_command(
        host,
        "if [ -d var/local_models ]; then find var/local_models -type f -printf '%s\\t%p\\n' | sort; fi",
        timeout=180,
    )

    (output_dir / "git-status-porcelain.txt").write_text(status, encoding="utf-8")
    (output_dir / "git-log.txt").write_text(log, encoding="utf-8")
    (output_dir / "tracked-working-tree.patch").write_text(tracked_patch, encoding="utf-8")
    (output_dir / "staged.patch").write_text(staged_patch, encoding="utf-8")
    (output_dir / "local-models-manifest.tsv").write_text(model_manifest, encoding="utf-8")

    # Stream all untracked content except the 16 GiB model weights and the
    # regenerable Go toolchain. Nothing is created, removed, or changed on AMD.
    archive_command = (
        "git ls-files --others --exclude-standard -z | "
        "grep -zvE '^(tools/go/|var/local_models/)' | "
        "tar --null --verbatim-files-from --files-from=- -czf -"
    )
    archive_bytes = bytes_command(host, archive_command, timeout=900)
    archive_path = output_dir / "amd-untracked-nonregenerable.tar.gz"
    archive_path.write_bytes(archive_bytes)

    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        archived_paths = [member.name for member in members if member.isfile() or member.issym()]

    metadata = {
        "version": "p0-amd-rescue-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "remote_read_only_local_snapshot",
        "production_mutated": False,
        "remote_files_created": False,
        "remote_files_deleted": False,
        "host": host,
        "attempts": attempts,
        "remote_repo": REMOTE_REPO,
        "branch": branch,
        "head": head,
        "status_line_count": len(status.splitlines()),
        "tracked_patch_bytes": len(tracked_patch.encode("utf-8")),
        "staged_patch_bytes": len(staged_patch.encode("utf-8")),
        "archive_path": str(archive_path.resolve()),
        "archive_bytes": archive_path.stat().st_size,
        "archive_sha256": sha256(archive_path),
        "archive_member_count": len(archived_paths),
        "excluded_regenerable_prefixes": list(EXCLUDED_REGENERABLE_PREFIXES),
        "model_manifest_path": str((output_dir / "local-models-manifest.tsv").resolve()),
        "snapshot_dir": str(output_dir.resolve()),
        "next_gate": "review rescue snapshot before creating any AMD rescue branch or clean deployment checkout",
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({"ok": True, **metadata}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
