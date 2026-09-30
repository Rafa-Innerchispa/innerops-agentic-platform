#!/usr/bin/env python3
"""Stage and classify runtime-only Python modules without mutating production.

Reads Intel locally and AMD over SSH. Snapshots are written only under the
canary checkout's ignored `.canary/` directory. The printed report contains
hashes, classifications, syntax status, symbol deltas, and secret-rule names;
it never prints secret values or source contents.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BRANCH_RUNTIME = ROOT / "platform" / "inneros_core_runtime"
INTEL_RUNTIME = Path(os.getenv("INNEROS_INTEL_RUNTIME", "/home/rlopez/inneros/inneros_core/platform/inneros_core_runtime"))
AMD_RUNTIME = os.getenv("INNEROS_AMD_RUNTIME", "/home/rlopez/inneros/inneros_core/platform/inneros_core_runtime")
AMD_HOSTS = tuple(dict.fromkeys(filter(None, (
    os.getenv("RALFIA_AMD_HOST", "100.72.153.124"),
    os.getenv("RALFIA_AMD_LAN_HOST", "192.168.1.5"),
))))

SECRET_RULES = {
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github_token": re.compile(rb"gh[pousr]_[A-Za-z0-9_]{20,}"),
    "openai_style_key": re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}"),
    "hardcoded_api_key": re.compile(rb"(?i)\bapi[_-]?key\s*=\s*['\"][^'\"\n]{8,}['\"]"),
    "hardcoded_password": re.compile(rb"(?i)\bpassword\s*=\s*['\"][^'\"\n]{8,}['\"]"),
    "hardcoded_token": re.compile(rb"(?i)\b(?:access_)?token\s*=\s*['\"][^'\"\n]{12,}['\"]"),
}


def sha(data: bytes | None) -> str | None:
    return hashlib.sha256(data).hexdigest() if data is not None else None


def read_optional(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def ssh(host: str, command: str, timeout: int = 25) -> dict[str, Any]:
    try:
        proc = subprocess.run([
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
            f"rlopez@{host}", command,
        ], capture_output=True, timeout=timeout, check=False)
        return {
            "ok": proc.returncode == 0,
            "stdout": proc.stdout,
            "error": proc.stderr.decode("utf-8", errors="replace").strip()[:300] or None,
        }
    except Exception as exc:
        return {"ok": False, "stdout": b"", "error": f"{type(exc).__name__}: {str(exc)[:240]}"}


def select_amd() -> tuple[str, list[dict[str, Any]]]:
    attempts = []
    for host in AMD_HOSTS:
        result = ssh(host, f"test -d '{AMD_RUNTIME}'")
        attempts.append({"host": host, "ok": result["ok"], "error": result.get("error")})
        if result["ok"]:
            return host, attempts
    raise SystemExit(json.dumps({"ok": False, "error": "amd_unreachable", "attempts": attempts}))


def inventory_local(root: Path) -> set[str]:
    return {str(path.relative_to(root)) for path in root.rglob("*.py") if path.is_file()}


def inventory_remote(host: str) -> set[str]:
    result = ssh(host, f"find '{AMD_RUNTIME}' -type f -name '*.py' -printf '%P\\n' 2>/dev/null | sort")
    if not result["ok"]:
        raise SystemExit(json.dumps({"ok": False, "error": "amd_inventory_failed", "detail": result.get("error")}))
    return set(result["stdout"].decode("utf-8", errors="replace").splitlines())


def remote_file(host: str, rel: str) -> bytes | None:
    result = ssh(host, f"cat '{AMD_RUNTIME}/{rel}'")
    return result["stdout"] if result["ok"] else None


def syntax_status(data: bytes | None, name: str) -> dict[str, Any]:
    if data is None:
        return {"present": False, "syntax_ok": False, "error": "missing"}
    try:
        compile(data.decode("utf-8", errors="strict"), name, "exec")
        return {"present": True, "syntax_ok": True, "error": None}
    except Exception as exc:
        return {"present": True, "syntax_ok": False, "error": f"{type(exc).__name__}: {str(exc)[:180]}"}


def secret_hits(data: bytes | None) -> list[dict[str, Any]]:
    if data is None:
        return []
    hits = []
    for rule, pattern in SECRET_RULES.items():
        for match in pattern.finditer(data):
            line = data.count(b"\n", 0, match.start()) + 1
            hits.append({"rule": rule, "line": line})
    return hits


def top_symbols(data: bytes | None) -> set[str]:
    if data is None:
        return set()
    try:
        tree = ast.parse(data.decode("utf-8", errors="strict"))
    except Exception:
        return set()
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def classify(branch: bytes | None, intel: bytes | None, amd: bytes | None) -> str:
    if branch is None:
        if intel is not None and amd is not None:
            return "runtime_only_common_identical" if intel == amd else "runtime_only_divergent"
        if intel is not None:
            return "runtime_only_intel"
        if amd is not None:
            return "runtime_only_amd"
        return "missing_everywhere"
    if intel is None or amd is None:
        return "tracked_missing_on_node"
    if branch == intel == amd:
        return "tracked_in_sync"
    if branch == intel and branch != amd:
        return "tracked_amd_drift"
    if branch == amd and branch != intel:
        return "tracked_intel_drift"
    return "tracked_three_way_drift"


def write_snapshot(base: Path, node: str, rel: str, data: bytes | None) -> str | None:
    if data is None:
        return None
    path = base / node / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


def main() -> None:
    branch_name = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch_name != "repair/coordination-recovery-20260929":
        raise SystemExit(f"REFUSED: expected repair branch, got {branch_name!r}")

    amd_host, attempts = select_amd()
    branch_inventory = inventory_local(BRANCH_RUNTIME)
    intel_inventory = inventory_local(INTEL_RUNTIME)
    amd_inventory = inventory_remote(amd_host)
    all_modules = sorted(branch_inventory | intel_inventory | amd_inventory)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    evidence = ROOT / ".canary" / "runtime-recovery" / stamp
    evidence.mkdir(parents=True, exist_ok=False)

    categories: dict[str, list[str]] = {}
    modules: dict[str, Any] = {}
    secret_summary: list[dict[str, Any]] = []

    for rel in all_modules:
        branch = read_optional(BRANCH_RUNTIME / rel)
        intel = read_optional(INTEL_RUNTIME / rel)
        amd = remote_file(amd_host, rel) if rel in amd_inventory else None
        category = classify(branch, intel, amd)
        categories.setdefault(category, []).append(rel)

        paths = {
            "intel": write_snapshot(evidence, "intel", rel, intel) if category != "tracked_in_sync" else None,
            "amd": write_snapshot(evidence, "amd", rel, amd) if category != "tracked_in_sync" else None,
        }
        checks = {
            "branch": syntax_status(branch, f"branch/{rel}"),
            "intel": syntax_status(intel, f"intel/{rel}"),
            "amd": syntax_status(amd, f"amd/{rel}"),
        }
        hits = {"intel": secret_hits(intel), "amd": secret_hits(amd)}
        for node, node_hits in hits.items():
            for hit in node_hits:
                secret_summary.append({"module": rel, "node": node, **hit})

        modules[rel] = {
            "classification": category,
            "hashes": {"branch": sha(branch), "intel": sha(intel), "amd": sha(amd)},
            "syntax": checks,
            "secret_rule_hits": hits,
            "snapshot_paths": paths,
        }

    symbol_deltas = {}
    for rel in ("mcp_server.py", "mcp_profiles.py"):
        branch = read_optional(BRANCH_RUNTIME / rel)
        intel = read_optional(INTEL_RUNTIME / rel)
        amd = remote_file(amd_host, rel)
        branch_symbols = top_symbols(branch)
        intel_symbols = top_symbols(intel)
        amd_symbols = top_symbols(amd)
        symbol_deltas[rel] = {
            "intel_added_vs_branch": sorted(intel_symbols - branch_symbols),
            "intel_removed_vs_branch": sorted(branch_symbols - intel_symbols),
            "amd_added_vs_branch": sorted(amd_symbols - branch_symbols),
            "amd_removed_vs_branch": sorted(branch_symbols - amd_symbols),
        }

    report = {
        "ok": not secret_summary and all(
            item["syntax"][node]["syntax_ok"]
            for item in modules.values()
            for node in ("intel", "amd")
            if item["syntax"][node]["present"]
        ),
        "mode": "read_only_runtime_recovery_staging",
        "production_mutated": False,
        "amd_host": amd_host,
        "amd_attempts": attempts,
        "evidence_dir": str(evidence),
        "inventory_counts": {
            "branch": len(branch_inventory),
            "intel": len(intel_inventory),
            "amd": len(amd_inventory),
        },
        "categories": {key: sorted(value) for key, value in sorted(categories.items())},
        "symbol_deltas": symbol_deltas,
        "secret_rule_hits": secret_summary,
        "modules": modules,
    }
    report_path = evidence / "report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    concise = {
        key: report[key]
        for key in (
            "ok", "mode", "production_mutated", "amd_host", "amd_attempts",
            "evidence_dir", "inventory_counts", "categories", "symbol_deltas",
            "secret_rule_hits",
        )
    }
    print(json.dumps(concise, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
