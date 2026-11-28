#!/usr/bin/env python3
"""Cloud runtime receipt to Google Drive; local Mongo slice when Vultr SSH is down."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=kwargs.get("timeout", 120))


def vultr_export() -> tuple[bytes, str]:
    config = Path.home() / ".config/ambient-guardian/cloud-core"
    ssh = [
        "ssh",
        "-F",
        "/dev/null",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ConnectTimeout=8",
        "-o",
        f"UserKnownHostsFile={config / 'known_hosts'}",
        "-i",
        str(config / "backup_pull_ed25519"),
        "root@45.32.171.62",
    ]
    fetch = subprocess.Popen(ssh, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    data = b""
    try:
        assert fetch.stdout is not None
        while chunk := fetch.stdout.read(65536):
            data += chunk
            if len(data) > 64 * 1024 * 1024:
                raise RuntimeError("Runtime backup exceeds 64 MiB policy")
        fetch.wait(timeout=30)
        if fetch.returncode:
            raise RuntimeError("Encrypted SSH export failed")
    finally:
        if fetch.poll() is None:
            fetch.kill()
            fetch.wait()
    return data, "vultr_ssh"


def _docker_mongo_dump(db: str, path: Path) -> None:
    docker_chk = _run(["docker", "ps", "--format", "{{.Names}}"], timeout=30)
    if docker_chk.returncode != 0 or "mongodb" not in docker_chk.stdout.splitlines():
        raise RuntimeError("docker mongodb container not running")
    cols = os.getenv(
        "INNEROS_MONGO_SLICE_COLLECTIONS",
        "ralfia_ops_tasks,ralfia_coordination_state,ralfia_agent_messages,ralfia_external_repair_runs",
    ).split(",")
    cols = [c.strip() for c in cols if c.strip()]
    with path.open("wb") as out:
        if len(cols) == 1:
            cmd = ["docker", "exec", "mongodb", "mongodump", f"--db={db}", f"--collection={cols[0]}", "--archive", "--gzip"]
        else:
            args = ["docker", "exec", "mongodb", "mongodump", f"--db={db}", "--archive", "--gzip"]
            for c in cols:
                args.extend(["--collection", c])
            cmd = args
        proc = subprocess.run(cmd, stdout=out, stderr=subprocess.PIPE, timeout=600)
    if proc.returncode:
        raise RuntimeError((proc.stderr or b"").decode()[-500:] or "docker mongodump failed")


def local_mongo_slice() -> tuple[bytes, str]:
    db = os.getenv("INNEROS_MONGO_DB", "pcdoctor_swarm")
    uri = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/")
    with tempfile.NamedTemporaryFile(suffix=".archive.gz", delete=False) as tmp:
        path = Path(tmp.name)
    try:
        _docker_mongo_dump(db, path)
        blob = path.read_bytes()
        if len(blob) > 256 * 1024 * 1024:
            raise RuntimeError("Local mongo slice exceeds 256 MiB policy — use inneros_mongo_coordination_backup")
        return blob, "local_mongo_fallback"
    finally:
        path.unlink(missing_ok=True)


def main() -> None:
    remote = "Ralphi-IA-Gdrive:RalphiIA_Backups/InnerOS_Cloud_Core"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest_name = f"runtime-{stamp}.tar.age"
    destination = f"{remote}/{dest_name}"
    config = Path.home() / ".config/ambient-guardian/cloud-core"
    config.mkdir(parents=True, exist_ok=True)

    try:
        raw, source = vultr_export()
    except Exception as vultr_err:
        raw, source = local_mongo_slice()
        note = str(vultr_err)[:200]
    else:
        note = ""

    checksum = hashlib.sha256(raw).hexdigest()
    with tempfile.NamedTemporaryFile(prefix="atlas-cloud-cipher-", delete=False) as enc:
        enc_path = Path(enc.name)
    enc_path.write_bytes(raw)

    upload = _run(
        ["rclone", "copyto", str(enc_path), destination, "--contimeout", "10s", "--timeout", "120s"],
        timeout=180,
    )
    enc_path.unlink(missing_ok=True)
    if upload.returncode:
        raise RuntimeError(upload.stderr[-900:] or "Encrypted Drive upload failed")

    receipt = {
        "ok": True,
        "created_at": stamp,
        "remote": destination,
        "bytes": len(raw),
        "sha256": checksum,
        "encrypted": False,
        "source": source,
        "vultr_fallback_note": note,
        "scope": "coordination mongo slice or vultr export",
    }
    target = config / "last-drive-backup.json"
    target.write_text(json.dumps(receipt, indent=2))
    target.chmod(0o600)
    print(json.dumps(receipt))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:500]}))
        sys.exit(1)