"""Narrow, SHA-bound host promotion of InnerOS source into its runtime.

This is not a general command runner. The only executable script is the
reviewed, fixed-path InnerOS runtime sync script, and no service is restarted.
"""
from __future__ import annotations

import re
from typing import Any

from inneros_core_runtime import local_execution_plane as lep
from inneros_core_runtime.agents import ag41_peer_ops_executor as ag41
from raphiia_openai.notifications import whatsapp_service_ops

REPO = "Rafa-Innerchispa/innerops-agentic-platform"
PROJECT_ID = "innerops-agentic-platform"
NODE = "primary"  # Intel staging first; AMD promotion requires a separate contract.
ROOT = "/home/rlopez/inneros/inneros_core/workspaces/innerops-agentic-platform"
SCRIPT = ROOT + "/platform/scripts/sync_platform_runtime_from_git.sh"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _safe(proc: Any) -> dict[str, Any]:
    return ag41._safe_proc(proc)


def _run(args: list[str], *, timeout: int = 90) -> Any:
    return ag41._run_node(NODE, args, timeout=timeout)


def promote(*, expected_sha: str, node: str = "primary",
            approval_id: str = "", dry_run: bool = True) -> dict[str, Any]:
    normalized = whatsapp_service_ops.normalize_node(node)
    if normalized != NODE:
        return {"ok": False, "error": "node_not_allowlisted", "allowed_node": NODE}
    if not isinstance(expected_sha, str) or not SHA_RE.fullmatch(expected_sha):
        return {"ok": False, "error": "full_expected_sha_required"}

    # Exact checkout verification is performed remotely, without a local shell.
    rev = _run(["git", "-C", ROOT, "rev-parse", "HEAD"], timeout=20)
    if rev.returncode != 0:
        return {"ok": False, "error": "source_checkout_unavailable", "diagnostic": _safe(rev)}
    actual_sha = (rev.stdout or "").strip()
    if actual_sha != expected_sha:
        return {
            "ok": False, "error": "source_sha_mismatch",
            "expected_sha": expected_sha, "actual_sha": actual_sha,
        }

    origin = _run(["git", "-C", ROOT, "remote", "get-url", "origin"], timeout=20)
    trusted_origins = {
        "https://github.com/Rafa-Innerchispa/innerops-agentic-platform",
        "https://github.com/Rafa-Innerchispa/innerops-agentic-platform.git",
        "git@github.com:Rafa-Innerchispa/innerops-agentic-platform.git",
    }
    if origin.returncode != 0 or (origin.stdout or "").strip() not in trusted_origins:
        return {"ok": False, "error": "noncanonical_source_origin"}

    approval: dict[str, Any] | None = None
    if not dry_run:
        if not approval_id:
            return {"ok": False, "error": "approval_id_required"}
        approval = lep.validate_host_approval(
            approval_id=approval_id,
            action="peer_inneros_runtime_promote",
            repo=REPO,
            project_id=PROJECT_ID,
            node=NODE,
        )
        if not approval.get("ok"):
            return {"ok": False, "error": "host_approval_invalid", "approval": approval}

    args = ["bash", SCRIPT, "--dry-run" if dry_run else "--apply"]
    if not dry_run:
        args += ["--expected-sha", expected_sha]
    result = _run(args, timeout=180 if dry_run else 900)
    output = _safe(result)
    if result.returncode != 0:
        return {
            "ok": False,
            "error": "sync_preflight_failed" if dry_run else "sync_apply_failed",
            "node": NODE, "source_sha": expected_sha,
            "diagnostic": output,
            "requires_manual_rollback_assessment": not dry_run,
        }
    log = str(result.stdout or "")
    if dry_run:
        if "DRY_RUN_OK" not in log:
            return {"ok": False, "error": "dry_run_marker_missing", "diagnostic": output}
        return {
            "ok": True, "dry_run": True, "node": NODE,
            "source_sha": expected_sha,
            "status": "preflight_pass",
            "diff": output,
            "service_reload_performed": False,
        }

    if f"SYNC_OK SHA={expected_sha}" not in log or "BACKUP=" not in log:
        return {"ok": False, "error": "sync_proof_missing", "diagnostic": output,
                "requires_manual_rollback_assessment": True}
    backup = next((line.split("=", 1)[1].strip() for line in log.splitlines()
                   if line.startswith("BACKUP=")), "")
    if not backup.startswith("/home/rlopez/inneros/inneros_core/var/runtime_sync_backups/"):
        return {"ok": False, "error": "untrusted_backup_path", "diagnostic": output,
                "requires_manual_rollback_assessment": True}
    ag41._audit_peer("peer_inneros_runtime_promote", {
        "node": NODE, "source_sha": expected_sha,
        "approval_id": approval_id, "backup": backup,
        "status": "staged_pending_service_reload",
    })
    return {
        "ok": True, "dry_run": False, "node": NODE,
        "source_sha": expected_sha, "backup": backup,
        "status": "staged_pending_service_reload",
        "service_reload_performed": False,
        "runtime_loaded_verified": False,
        "next_gate": "Separate approved service restart, health canaries and actual loaded SHA verification",
        "approval": approval,
    }
