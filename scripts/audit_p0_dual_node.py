#!/usr/bin/env python3
"""Read-only P0 parity audit for Intel .4, AMD .5, and MCP Small.

This script never restarts services, changes files, writes databases, or deploys.
It compares live HTTP metadata, deployed Git state, and critical runtime file
hashes on both InnerOS nodes. Secrets and environment values are not printed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request
from typing import Any

INTEL_HOST = os.getenv("RALFIA_INTEL_HOST", "192.168.1.4")
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
MCP_PORT = int(os.getenv("MCP_PORT", "8102"))
LIVE_REPO = Path(os.getenv("INNEROS_LIVE_REPO", "/home/rlopez/inneros/inneros_core"))
PUBLIC_MCP_SMALL = os.getenv("INNEROS_MCP_SMALL_URL", "https://mcp.pcdoctor.ai/router/mcp")
OAUTH_METADATA_URL = f"{PUBLIC_MCP_SMALL}/.well-known/oauth-protected-resource"

CRITICAL_FILES = (
    "platform/inneros_core_runtime/mcp_server.py",
    "platform/inneros_core_runtime/mcp_profiles.py",
    "platform/inneros_core_runtime/mcp_diagnostics.py",
    "platform/inneros_core_runtime/mcp_fleet.py",
    "platform/inneros_core_runtime/settings.py",
    "platform/inneros_core_runtime/oauth_metadata.py",
    "platform/inneros_core_runtime/oauth_store.py",
    "platform/inneros_core_runtime/inneros_auth_middleware.py",
    "platform/inneros_core_runtime/coordination_live.py",
    "platform/inneros_core_runtime/durable_coordination_spine.py",
    "platform/inneros_core_runtime/temporal_worker.py",
    "platform/inneros_core_runtime/temporal_workflows.py",
    "platform/inneros_core_runtime/temporal_activities.py",
    "platform/inneros_core_runtime/dev_swarm_scheduler.py",
    "platform/inneros_core_runtime/local_execution_plane.py",
    "platform/inneros_core_runtime/agent_identity.py",
    "platform/inneros_core_runtime/memory/agent_messages.py",
)


def http_json(url: str, timeout: float = 6) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "inneros-p0-parity-audit/1.1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {
                "ok": response.status == 200,
                "status": response.status,
                "data": json.loads(response.read().decode("utf-8", errors="replace")),
            }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:240]}"}


def run_local(*args: str) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            list(args), cwd=LIVE_REPO, text=True, capture_output=True, timeout=12, check=False
        )
        return {
            "ok": proc.returncode == 0,
            "stdout": proc.stdout.strip(),
            "error": proc.stderr.strip()[:300] or None,
        }
    except Exception as exc:
        return {"ok": False, "stdout": "", "error": f"{type(exc).__name__}: {str(exc)[:240]}"}


def run_remote(host: str, command: str) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            [
                "ssh",
                "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=5",
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                f"rlopez@{host}",
                f"cd {LIVE_REPO} && {command}",
            ],
            text=True,
            capture_output=True,
            timeout=18,
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "stdout": proc.stdout.strip(),
            "error": proc.stderr.strip()[:300] or None,
        }
    except Exception as exc:
        return {"ok": False, "stdout": "", "error": f"{type(exc).__name__}: {str(exc)[:240]}"}


def sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def local_git_and_hashes() -> dict[str, Any]:
    head = run_local("git", "rev-parse", "HEAD")
    branch = run_local("git", "branch", "--show-current")
    status = run_local("git", "status", "--porcelain")
    hashes = {rel: sha256_file(LIVE_REPO / rel) for rel in CRITICAL_FILES}
    return {
        "reachable": LIVE_REPO.is_dir(),
        "git_metadata_available": bool(head.get("ok")),
        "head": head.get("stdout") or None,
        "branch": branch.get("stdout") or None,
        "clean": bool(status.get("ok") and not status.get("stdout")),
        "status_count": len((status.get("stdout") or "").splitlines()),
        "hashes": hashes,
        "errors": [item.get("error") for item in (head, branch, status) if not item.get("ok")],
    }


def remote_git_and_hashes(host: str) -> dict[str, Any]:
    head = run_remote(host, "git rev-parse HEAD")
    branch = run_remote(host, "git branch --show-current")
    status = run_remote(host, "git status --porcelain")
    quoted = " ".join(f"'{rel}'" for rel in CRITICAL_FILES)
    sums = run_remote(host, f"sha256sum {quoted} 2>/dev/null || true")
    hashes = {rel: None for rel in CRITICAL_FILES}
    for line in (sums.get("stdout") or "").splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and parts[1] in hashes:
            hashes[parts[1]] = parts[0]
    return {
        "reachable": bool(head.get("ok") or sums.get("stdout")),
        "git_metadata_available": bool(head.get("ok")),
        "host": host,
        "head": head.get("stdout") or None,
        "branch": branch.get("stdout") or None,
        "clean": bool(status.get("ok") and not status.get("stdout")),
        "status_count": len((status.get("stdout") or "").splitlines()),
        "hashes": hashes,
        "errors": [item.get("error") for item in (head, branch, status, sums) if not item.get("ok")],
    }


def first_reachable_amd_runtime() -> dict[str, Any]:
    attempts = []
    for host in AMD_HOSTS:
        snapshot = remote_git_and_hashes(host)
        attempts.append({"host": host, "reachable": snapshot["reachable"]})
        if snapshot["reachable"]:
            snapshot["attempts"] = attempts
            return snapshot
    return {
        "reachable": False,
        "git_metadata_available": False,
        "host": None,
        "head": None,
        "branch": None,
        "clean": False,
        "status_count": 0,
        "hashes": {rel: None for rel in CRITICAL_FILES},
        "errors": ["AMD checkout not reachable through configured hosts"],
        "attempts": attempts,
    }


def mcp_snapshot(host: str) -> dict[str, Any]:
    result = http_json(f"http://{host}:{MCP_PORT}/version")
    data = result.get("data") or {}
    return {
        "ok": result.get("ok", False),
        "host": host,
        "server_version": data.get("server_version"),
        "catalog_version": data.get("catalog_version"),
        "tool_count": data.get("tool_count") or data.get("runtime_tool_count") or data.get("catalog_tool_count"),
        "manifest_hash": data.get("manifest_hash"),
        "error": result.get("error"),
    }


def first_healthy_amd_mcp() -> dict[str, Any]:
    attempts = []
    first = None
    for host in AMD_HOSTS:
        snapshot = mcp_snapshot(host)
        attempts.append({"host": host, "ok": snapshot["ok"], "error": snapshot.get("error")})
        if first is None:
            first = snapshot
        if snapshot["ok"]:
            snapshot["attempts"] = attempts
            return snapshot
    result = first or mcp_snapshot(AMD_HOSTS[0])
    result["attempts"] = attempts
    return result


def same_nonempty(left: Any, right: Any) -> bool:
    return left is not None and right is not None and left == right


def main() -> None:
    intel_runtime = local_git_and_hashes()
    amd_runtime = first_reachable_amd_runtime()
    intel_mcp = mcp_snapshot(INTEL_HOST)
    amd_mcp = first_healthy_amd_mcp()
    public_probe = http_json(PUBLIC_MCP_SMALL)
    oauth_probe = http_json(OAUTH_METADATA_URL)

    divergences = []
    for rel in CRITICAL_FILES:
        intel_hash = intel_runtime["hashes"].get(rel)
        amd_hash = amd_runtime["hashes"].get(rel)
        if not same_nonempty(intel_hash, amd_hash):
            divergences.append({"file": rel, "intel": intel_hash, "amd": amd_hash})

    oauth_data = oauth_probe.get("data") or {}
    public_data = public_probe.get("data") or {}
    gates = {
        "both_mcp_up": bool(intel_mcp["ok"] and amd_mcp["ok"]),
        "same_server_version": same_nonempty(intel_mcp["server_version"], amd_mcp["server_version"]),
        "same_catalog_version": same_nonempty(intel_mcp["catalog_version"], amd_mcp["catalog_version"]),
        "same_tool_count": same_nonempty(intel_mcp["tool_count"], amd_mcp["tool_count"]),
        "same_manifest_hash": same_nonempty(intel_mcp["manifest_hash"], amd_mcp["manifest_hash"]),
        "git_metadata_available": bool(
            intel_runtime["git_metadata_available"] and amd_runtime["git_metadata_available"]
        ),
        "same_git_head": same_nonempty(intel_runtime["head"], amd_runtime["head"]),
        "clean_checkouts": bool(intel_runtime["clean"] and amd_runtime["clean"]),
        "same_critical_hashes": not divergences,
        "public_router_ok": bool(
            public_probe.get("ok")
            and public_data.get("service") == "mcp-router-gateway"
            and public_data.get("profile") == "chatgpt_compact"
        ),
        "oauth_metadata_exact": bool(
            oauth_probe.get("ok")
            and oauth_data.get("resource") == PUBLIC_MCP_SMALL
            and oauth_data.get("router_profile") == "chatgpt_compact"
        ),
    }
    report = {
        "ok": all(gates.values()),
        "mode": "read_only_dual_node_parity_audit",
        "production_mutated": False,
        "gates": gates,
        "nodes": {
            "intel": {"mcp": intel_mcp, "runtime": intel_runtime},
            "amd": {"mcp": amd_mcp, "runtime": amd_runtime},
        },
        "critical_file_divergences": divergences,
        "public_mcp_small": {
            "url": PUBLIC_MCP_SMALL,
            "ok": public_probe.get("ok", False),
            "service": public_data.get("service"),
            "profile": public_data.get("profile"),
        },
        "oauth": {
            "metadata_url": OAUTH_METADATA_URL,
            "ok": oauth_probe.get("ok", False),
            "resource": oauth_data.get("resource"),
            "authorization_servers": oauth_data.get("authorization_servers"),
            "router_profile": oauth_data.get("router_profile"),
        },
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
