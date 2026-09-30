#!/usr/bin/env python3
"""Capture sanitized Intel/AMD runtime drift evidence into the canary checkout.

Production is read-only. Source snapshots and patches are written only beneath
`.canary/`, which is gitignored. The JSON report prints hashes, line counts, and
module inventory differences; it never prints source contents or secrets.
"""
from __future__ import annotations

from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BRANCH_RUNTIME = ROOT / "platform" / "inneros_core_runtime"
INTEL_RUNTIME = Path(
    os.getenv(
        "INNEROS_INTEL_RUNTIME",
        "/home/rlopez/inneros/inneros_core/platform/inneros_core_runtime",
    )
)
AMD_RUNTIME = os.getenv(
    "INNEROS_AMD_RUNTIME",
    "/home/rlopez/inneros/inneros_core/platform/inneros_core_runtime",
)
AMD_HOSTS = tuple(
    dict.fromkeys(
        host
        for host in (
            os.getenv("RALFIA_AMD_HOST", "100.72.153.124"),
            os.getenv("RALFIA_AMD_LAN_HOST", "192.168.1.5"),
        )
        if host
    )
)
TARGETS = ("mcp_server.py", "mcp_profiles.py")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ssh_bytes(host: str, command: str, timeout: int = 20) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            [
                "ssh",
                "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=5",
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                f"rlopez@{host}",
                command,
            ],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "stdout": proc.stdout,
            "error": proc.stderr.decode("utf-8", errors="replace").strip()[:300] or None,
        }
    except Exception as exc:
        return {"ok": False, "stdout": b"", "error": f"{type(exc).__name__}: {str(exc)[:240]}"}


def select_amd_host() -> tuple[str | None, list[dict[str, Any]]]:
    attempts = []
    for host in AMD_HOSTS:
        result = ssh_bytes(host, f"test -d '{AMD_RUNTIME}'")
        attempts.append({"host": host, "ok": result["ok"], "error": result.get("error")})
        if result["ok"]:
            return host, attempts
    return None, attempts


def unified_patch(branch: bytes, runtime: bytes, branch_name: str, runtime_name: str) -> tuple[str, int, int]:
    before = branch.decode("utf-8", errors="replace").splitlines(keepends=True)
    after = runtime.decode("utf-8", errors="replace").splitlines(keepends=True)
    patch_lines = list(
        difflib.unified_diff(before, after, fromfile=branch_name, tofile=runtime_name, n=3)
    )
    added = sum(1 for line in patch_lines if line.startswith("+") and not line.startswith("+++"))
    deleted = sum(1 for line in patch_lines if line.startswith("-") and not line.startswith("---"))
    return "".join(patch_lines), added, deleted


def local_inventory(root: Path) -> set[str]:
    return {str(path.relative_to(root)) for path in root.rglob("*.py") if path.is_file()}


def remote_inventory(host: str) -> tuple[set[str], str | None]:
    result = ssh_bytes(
        host,
        f"find '{AMD_RUNTIME}' -type f -name '*.py' -printf '%P\\n' 2>/dev/null | sort",
    )
    if not result["ok"]:
        return set(), result.get("error")
    return set(result["stdout"].decode("utf-8", errors="replace").splitlines()), None


def main() -> None:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != "repair/coordination-recovery-20260929":
        raise SystemExit(f"REFUSED: expected repair branch, got {branch!r}")
    if not BRANCH_RUNTIME.is_dir() or not INTEL_RUNTIME.is_dir():
        raise SystemExit("REFUSED: branch or Intel runtime path missing")

    amd_host, attempts = select_amd_host()
    if not amd_host:
        raise SystemExit(json.dumps({"ok": False, "error": "amd_runtime_unreachable", "attempts": attempts}))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    evidence_dir = ROOT / ".canary" / "runtime-drift" / stamp
    evidence_dir.mkdir(parents=True, exist_ok=False)

    report: dict[str, Any] = {
        "ok": True,
        "mode": "read_only_runtime_drift_capture",
        "production_mutated": False,
        "amd_host": amd_host,
        "amd_attempts": attempts,
        "evidence_dir": str(evidence_dir),
        "files": {},
    }

    for target in TARGETS:
        branch_bytes = (BRANCH_RUNTIME / target).read_bytes()
        intel_bytes = (INTEL_RUNTIME / target).read_bytes()
        amd_result = ssh_bytes(amd_host, f"cat '{AMD_RUNTIME}/{target}'")
        if not amd_result["ok"]:
            report["ok"] = False
            report["files"][target] = {"error": amd_result.get("error")}
            continue
        amd_bytes = amd_result["stdout"]

        file_report: dict[str, Any] = {
            "hashes": {
                "branch": digest(branch_bytes),
                "intel": digest(intel_bytes),
                "amd": digest(amd_bytes),
            },
            "matches": {
                "intel_branch": branch_bytes == intel_bytes,
                "amd_branch": branch_bytes == amd_bytes,
                "intel_amd": intel_bytes == amd_bytes,
            },
        }
        for node, runtime_bytes in (("intel", intel_bytes), ("amd", amd_bytes)):
            snapshot = evidence_dir / node / target
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_bytes(runtime_bytes)
            patch, added, deleted = unified_patch(
                branch_bytes,
                runtime_bytes,
                f"branch/{target}",
                f"{node}/{target}",
            )
            patch_path = evidence_dir / f"{node}_{target}.patch"
            patch_path.write_text(patch, encoding="utf-8")
            file_report[f"{node}_diff"] = {
                "added_lines": added,
                "deleted_lines": deleted,
                "patch_path": str(patch_path),
            }
        report["files"][target] = file_report

    branch_modules = local_inventory(BRANCH_RUNTIME)
    intel_modules = local_inventory(INTEL_RUNTIME)
    amd_modules, amd_inventory_error = remote_inventory(amd_host)
    report["module_inventory"] = {
        "counts": {
            "branch": len(branch_modules),
            "intel": len(intel_modules),
            "amd": len(amd_modules),
        },
        "intel_only": sorted(intel_modules - branch_modules),
        "branch_missing_on_intel": sorted(branch_modules - intel_modules),
        "amd_only": sorted(amd_modules - branch_modules),
        "branch_missing_on_amd": sorted(branch_modules - amd_modules),
        "amd_inventory_error": amd_inventory_error,
    }

    report_path = evidence_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
