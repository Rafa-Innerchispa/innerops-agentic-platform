"""Bounded host deployment for the InfraLens MC2 judge presentation.

This module intentionally supports one product/deployment contract only. It is
not a generic Docker shell. Every mutation is project-scoped, approval-scoped,
audited, and rollback-capable.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from inneros_core_runtime import local_execution_plane as lep
from inneros_core_runtime.agents import ag41_peer_ops_executor as ag41
from raphiia_openai import project_runtime_registry as prr
from raphiia_openai.notifications import whatsapp_service_ops


POLICY = {
    "repo": "Rafa-Innerchispa/infralens-ocr-amd",
    "project_id": "infralens-ocr-amd",
    "node": "amd",
    "compose_file": "docker-compose.presentation.yml",
    "services": ("vision-backend", "streamlit-ui"),
    "containers": ("infralens-track2-ocr", "infralens-track2-ui"),
    "final_image": "us-central1-docker.pkg.dev/innerops-agentic-platform/amd-academy-public/chispavision-mc2:final-512",
    "final_digest": "sha256:dbfcaf89fc2d47823406c1ceeefef464a98a7e4328226511ab1625c3d721868f",
    "health_url": "http://127.0.0.1:18765/health",
    "analyze_url": "http://127.0.0.1:18765/analyze",
    "ocr_url": "http://127.0.0.1:18765/ocr",
    "ui_health_url": "http://127.0.0.1:18501/_stcore/health",
    "public_url": "https://infralens.creatorcore.ai/",
}


def _safe_proc(proc) -> dict[str, Any]:
    return ag41._safe_proc(proc)


def _run(node: str, args: list[str], *, timeout: int = 60, input_text: str | None = None):
    return ag41._run_node(node, args, timeout=timeout, input_text=input_text)


def _under_roots(path: Path, roots: list[str]) -> bool:
    resolved = path.expanduser().resolve()
    for root in roots:
        r = Path(root).expanduser().resolve()
        if resolved == r or r in resolved.parents:
            return True
    return False


def _container_snapshot(node: str, name: str) -> dict[str, Any]:
    proc = _run(
        node,
        ["docker", "inspect", "--format", "{{.Id}}|{{.Image}}|{{.Config.Image}}|{{.State.Running}}", name],
        timeout=20,
    )
    if proc.returncode != 0:
        return {"ok": False, "name": name, "error": "container_inspect_failed", "raw": _safe_proc(proc)}
    parts = (proc.stdout or "").strip().split("|", 3)
    if len(parts) != 4:
        return {"ok": False, "name": name, "error": "container_inspect_parse_failed", "raw": _safe_proc(proc)}
    return {
        "ok": True,
        "name": name,
        "container_id": parts[0],
        "image_id": parts[1],
        "image_ref": parts[2],
        "running": parts[3].strip().lower() == "true",
    }


def _image_id(node: str, image_ref: str) -> dict[str, Any]:
    proc = _run(node, ["docker", "image", "inspect", "--format", "{{.Id}}", image_ref], timeout=30)
    return {
        "ok": proc.returncode == 0,
        "image_ref": image_ref,
        "image_id": (proc.stdout or "").strip(),
        "raw": _safe_proc(proc),
    }


def _curl(
    node: str,
    url: str,
    *,
    timeout: int = 20,
    headers: list[str] | None = None,
    body: str | None = None,
) -> dict[str, Any]:
    args = ["curl", "-fsS", "--max-time", str(max(1, min(timeout, 120)))]
    for header in headers or []:
        args.extend(["-H", header])
    if body is not None:
        args.extend(["--data-binary", "@-"])
    args.append(url)
    proc = _run(node, args, timeout=timeout + 10, input_text=body)
    return {
        "ok": proc.returncode == 0,
        "url": url,
        "stdout": ag41._redact((proc.stdout or "")[:16000]),
        "stderr": ag41._redact((proc.stderr or "")[:3000]),
        "returncode": proc.returncode,
    }


def _approval(approval_id: str, node: str) -> dict[str, Any]:
    return lep.validate_host_approval(
        approval_id=approval_id,
        action="peer_infralens_presentation_deploy",
        repo=POLICY["repo"],
        project_id=POLICY["project_id"],
        node=node,
    )


def _restore(node: str, compose_path: str, backups: dict[str, str]) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    down = _run(node, ["docker", "compose", "-f", compose_path, "down"], timeout=120)
    steps.append({"step": "compose_down_new", **_safe_proc(down)})
    ok = True
    for original, backup in backups.items():
        current = _run(node, ["docker", "inspect", original], timeout=15)
        if current.returncode == 0:
            rm = _run(node, ["docker", "rm", "-f", original], timeout=45)
            steps.append({"step": f"remove_new:{original}", **_safe_proc(rm)})
            ok = ok and rm.returncode == 0
        rename = _run(node, ["docker", "rename", backup, original], timeout=30)
        steps.append({"step": f"restore_name:{original}", **_safe_proc(rename)})
        if rename.returncode != 0:
            ok = False
            continue
        start = _run(node, ["docker", "start", original], timeout=60)
        steps.append({"step": f"restart_old:{original}", **_safe_proc(start)})
        ok = ok and start.returncode == 0
    return {"ok": ok, "steps": steps}


def deploy(
    *,
    node: str = "amd",
    source_path: str,
    expected_sha: str,
    approval_id: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    node = whatsapp_service_ops.normalize_node(node)
    if node != POLICY["node"]:
        return {"ok": False, "error": "node_not_allowlisted", "allowed_node": POLICY["node"]}
    if not approval_id:
        return {"ok": False, "error": "approval_id_required"}

    approval = _approval(approval_id, node)
    if not approval.get("ok"):
        return {"ok": False, "error": "host_approval_invalid", "approval": approval}

    source = Path(source_path or "").expanduser().resolve()
    roots = prr.trusted_roots(node)
    if not source_path or not _under_roots(source, roots):
        return {"ok": False, "error": "source_path_not_under_trusted_root", "trusted_roots": roots}
    if source.is_symlink():
        return {"ok": False, "error": "source_path_symlink_denied"}

    compose = (source / POLICY["compose_file"]).resolve()
    if compose.parent != source or not compose.is_file():
        return {"ok": False, "error": "presentation_compose_missing", "compose_path": str(compose)}

    rev = _run(node, ["git", "-C", str(source), "rev-parse", "HEAD"], timeout=20)
    if rev.returncode != 0:
        return {"ok": False, "error": "source_git_head_unavailable", "raw": _safe_proc(rev)}
    source_sha = (rev.stdout or "").strip()
    if not expected_sha or source_sha != expected_sha.strip():
        return {
            "ok": False,
            "error": "source_sha_mismatch",
            "expected_sha": expected_sha.strip(),
            "actual_sha": source_sha,
        }

    old = {name: _container_snapshot(node, name) for name in POLICY["containers"]}
    if not all(item.get("ok") for item in old.values()):
        return {"ok": False, "error": "current_container_snapshot_failed", "containers": old}

    final_before = _image_id(node, POLICY["final_image"])
    if not final_before.get("ok") or final_before.get("image_id") != POLICY["final_digest"]:
        return {
            "ok": False,
            "error": "immutable_final512_digest_mismatch",
            "expected": POLICY["final_digest"],
            "actual": final_before.get("image_id"),
        }

    plan = {
        "source_path": str(source),
        "source_sha": source_sha,
        "compose_path": str(compose),
        "services": list(POLICY["services"]),
        "containers": old,
        "immutable_final512": final_before.get("image_id"),
    }
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "would_execute": "build -> stop/rename old -> compose up -> health/analyze/ocr/ui/public -> preserve rollback containers",
            "plan": plan,
            "approval": approval,
        }

    build = _run(
        node,
        ["docker", "compose", "-f", str(compose), "build", *POLICY["services"]],
        timeout=1800,
    )
    if build.returncode != 0:
        return {"ok": False, "error": "presentation_build_failed", "build": _safe_proc(build), "plan": plan}

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backups: dict[str, str] = {}
    cutover: list[dict[str, Any]] = []

    for name in POLICY["containers"]:
        backup = f"{name}-rollback-{stamp}"
        stop = _run(node, ["docker", "stop", name], timeout=90)
        cutover.append({"step": f"stop:{name}", **_safe_proc(stop)})
        if stop.returncode != 0:
            rollback = _restore(node, str(compose), backups) if backups else {"ok": True, "steps": []}
            return {"ok": False, "error": "old_container_stop_failed", "container": name, "cutover": cutover, "rollback": rollback}

        rename = _run(node, ["docker", "rename", name, backup], timeout=30)
        cutover.append({"step": f"rename:{name}", "backup_name": backup, **_safe_proc(rename)})
        if rename.returncode != 0:
            _run(node, ["docker", "start", name], timeout=60)
            rollback = _restore(node, str(compose), backups) if backups else {"ok": True, "steps": []}
            return {"ok": False, "error": "old_container_rename_failed", "container": name, "cutover": cutover, "rollback": rollback}
        backups[name] = backup

    up = _run(node, ["docker", "compose", "-f", str(compose), "up", "-d", "--no-build"], timeout=180)
    cutover.append({"step": "compose_up", **_safe_proc(up)})
    if up.returncode != 0:
        rollback = _restore(node, str(compose), backups)
        return {"ok": False, "error": "presentation_compose_up_failed", "cutover": cutover, "rollback": rollback}

    time.sleep(8)
    health = _curl(node, POLICY["health_url"], timeout=20)
    ui = _curl(node, POLICY["ui_health_url"], timeout=20)
    tiny_ppm = "P3\n1 1\n255\n255 255 255\n"
    analyze = _curl(
        node,
        POLICY["analyze_url"],
        timeout=90,
        headers=["Content-Type: application/octet-stream", "X-InfraLens-Task: general"],
        body=tiny_ppm,
    )
    ocr = _curl(
        node,
        POLICY["ocr_url"],
        timeout=90,
        headers=["Content-Type: application/octet-stream"],
        body=tiny_ppm,
    )
    public = _curl(node, POLICY["public_url"], timeout=25)

    try:
        health_json = json.loads(health.get("stdout") or "{}") if health.get("ok") else {}
    except Exception:
        health_json = {}
    try:
        analyze_json = json.loads(analyze.get("stdout") or "{}") if analyze.get("ok") else {}
    except Exception:
        analyze_json = {}

    final_after = _image_id(node, POLICY["final_image"])
    new = {name: _container_snapshot(node, name) for name in POLICY["containers"]}

    checks = {
        "health_http": health.get("ok"),
        "visual_analysis_capability": "visual_analysis" in (health_json.get("capabilities") or []),
        "analyze_http": analyze.get("ok"),
        "analyze_contract": isinstance(analyze_json.get("analysis"), dict) and isinstance(analyze_json.get("runtime"), dict),
        "ocr_http": ocr.get("ok"),
        "ui_health": ui.get("ok") and "ok" in (ui.get("stdout") or "").lower(),
        "public_https": public.get("ok"),
        "final512_unchanged": final_after.get("image_id") == POLICY["final_digest"],
        "new_containers_running": all(item.get("ok") and item.get("running") for item in new.values()),
    }

    verification = {
        "checks": checks,
        "health": {**health, "json": health_json},
        "analyze": {**analyze, "json": analyze_json},
        "ocr": ocr,
        "ui": ui,
        "public_http": public,
        "immutable_final512_after": final_after,
        "new_containers": new,
    }

    if not all(checks.values()):
        rollback = _restore(node, str(compose), backups)
        return {
            "ok": False,
            "error": "presentation_verification_failed",
            "source_sha": source_sha,
            "old_containers": old,
            "new_containers": new,
            "verification": verification,
            "rollback": rollback,
        }

    evidence = {
        "source_sha": source_sha,
        "old_image_ids": {name: item.get("image_id") for name, item in old.items()},
        "new_image_ids": {name: item.get("image_id") for name, item in new.items()},
        "rollback_containers": backups,
        "health": health_json,
        "analyze": {
            "keys": sorted(analyze_json.keys()),
            "task": (analyze_json.get("analysis") or {}).get("task"),
        },
        "public_http": {"ok": public.get("ok"), "url": public.get("url")},
        "rollback_status": "not_needed_backups_preserved",
        "immutable_final512": final_after.get("image_id"),
    }
    ag41._audit_peer(
        "peer_infralens_presentation_deploy",
        {
            "ok": True,
            "node": node,
            "source_sha": source_sha,
            "approval_id": approval_id,
            "rollback_containers": backups,
        },
    )
    return {
        "ok": True,
        "node": node,
        "source_path": str(source),
        "compose_path": str(compose),
        "evidence": evidence,
        "verification": verification,
        "cutover": cutover,
    }
