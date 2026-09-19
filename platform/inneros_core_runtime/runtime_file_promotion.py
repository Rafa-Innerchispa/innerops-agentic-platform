"""Narrow, auditable promotion of selected platform runtime files.

This module exists for one purpose: copy a reviewed file from the registered
InnerOps platform workspace into the active local runtime without exposing file
contents, syncing whole trees, or overwriting unrelated node drift.

Promotion is guarded by:
- a fixed source repository/project;
- a strict relative-path allowlist;
- source and target SHA-256 preconditions;
- a short-lived scoped host approval;
- a byte-for-byte backup before replacement;
- atomic replacement and post-write hash verification.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CAPABILITY = "runtime_file_promotion"
PLATFORM_REPO = "Rafa-Innerchispa/innerops-agentic-platform"
PLATFORM_PROJECT_ID = "innerops-agentic-platform"
ACTIVE_ROOT = Path("/home/rlopez/inneros/inneros_core/platform")
BACKUP_ROOT = Path("/home/rlopez/inneros/inneros_core/var/runtime_promotion_backups")
ALLOWED_PREFIXES = ("inneros_core_runtime/", "raphiia_openai/")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative_path(relative_path: str) -> Path:
    raw = str(relative_path or "").strip().replace("\\", "/")
    if not raw:
        raise ValueError("relative_path_required")
    rel = Path(raw)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("relative_path_invalid")
    normalized = rel.as_posix()
    if not any(normalized.startswith(prefix) for prefix in ALLOWED_PREFIXES):
        raise PermissionError("relative_path_not_allowlisted")
    return rel


def _require_platform_identity(project_id: str, repo: str) -> None:
    if str(project_id or "") != PLATFORM_PROJECT_ID:
        raise PermissionError("project_not_allowlisted")
    if str(repo or "") != PLATFORM_REPO:
        raise PermissionError("repo_not_allowlisted")


def _workspace_platform_root(project_id: str, repo: str, node: str) -> Path:
    _require_platform_identity(project_id, repo)
    from raphiia_openai import project_runtime_registry

    resolved = project_runtime_registry.resolve_project(
        project_id=project_id,
        repo=repo,
        node=node,
    )
    if not resolved.get("ok"):
        raise ValueError(resolved.get("error") or "project_runtime_unavailable")
    project_path = Path(str(resolved.get("project_path") or "")).expanduser().resolve()
    platform_root = (project_path / "platform").resolve()
    if project_path not in platform_root.parents:
        raise PermissionError("workspace_platform_escape")
    return platform_root


def _validate_host_approval(
    *,
    approval_id: str,
    action: str,
    repo: str,
    project_id: str,
    node: str,
) -> dict[str, Any]:
    from inneros_core_runtime import local_execution_plane

    return local_execution_plane.validate_host_approval(
        approval_id=approval_id,
        action=action,
        repo=repo,
        project_id=project_id,
        node=node,
    )


def _target_path(relative_path: str) -> tuple[Path, Path]:
    rel = _safe_relative_path(relative_path)
    active_root = ACTIVE_ROOT.expanduser().resolve()
    target = (active_root / rel).resolve()
    if active_root not in target.parents:
        raise PermissionError("active_runtime_escape")
    return rel, target


def _audit(action: str, result: dict[str, Any], metadata: dict[str, Any]) -> None:
    try:
        from raphiia_openai import mongo_store

        mongo_store.log_coordination(
            agent=str(metadata.get("actor") or "SYSTEM").upper(),
            event="runtime_file_promotion",
            summary=f"{action}: {metadata.get('relative_path') or ''}",
            project="innerops-agentic-platform",
            tool_used=f"{CAPABILITY}.{action}",
            metadata={
                "capability": CAPABILITY,
                "action": action,
                "result": {k: v for k, v in result.items() if k not in {"content"}},
                "metadata": {
                    k: v
                    for k, v in metadata.items()
                    if k not in {"approval_id"}
                },
                "at": _now_iso(),
            },
        )
    except Exception:
        pass


def plan_promotion(
    *,
    project_id: str,
    repo: str,
    relative_path: str,
    node: str = "primary",
) -> dict[str, Any]:
    try:
        source_root = _workspace_platform_root(project_id, repo, node)
        rel, target = _target_path(relative_path)
        source = (source_root / rel).resolve()
        if source_root not in source.parents:
            raise PermissionError("workspace_source_escape")
        if not source.is_file():
            return {"ok": False, "error": "source_file_missing", "source_path": str(source)}
        if not target.is_file():
            return {"ok": False, "error": "target_file_missing", "target_path": str(target)}

        source_hash = _sha256(source)
        target_hash = _sha256(target)
        return {
            "ok": True,
            "capability": CAPABILITY,
            "project_id": project_id,
            "repo": repo,
            "node": node,
            "relative_path": rel.as_posix(),
            "source_path": str(source),
            "target_path": str(target),
            "source_sha256": source_hash,
            "target_sha256": target_hash,
            "source_bytes": source.stat().st_size,
            "target_bytes": target.stat().st_size,
            "would_change": source_hash != target_hash,
        }
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}


def apply_promotion(
    *,
    project_id: str,
    repo: str,
    relative_path: str,
    expected_source_sha256: str,
    expected_target_sha256: str,
    approval_id: str,
    actor: str,
    task_id: str,
    correlation_id: str,
    node: str = "primary",
    dry_run: bool = True,
) -> dict[str, Any]:
    metadata = {
        "project_id": project_id,
        "repo": repo,
        "relative_path": relative_path,
        "node": node,
        "actor": actor,
        "task_id": task_id,
        "correlation_id": correlation_id,
    }
    try:
        if not all(str(x or "").strip() for x in (expected_source_sha256, expected_target_sha256, approval_id, actor, task_id, correlation_id)):
            raise ValueError("promotion_preconditions_required")

        approval = _validate_host_approval(
            approval_id=approval_id,
            action="runtime_file_promote",
            repo=repo,
            project_id=project_id,
            node=node,
        )
        if not approval.get("ok"):
            return {"ok": False, "capability": CAPABILITY, "error": approval.get("error") or "approval_invalid"}

        plan = plan_promotion(
            project_id=project_id,
            repo=repo,
            relative_path=relative_path,
            node=node,
        )
        if not plan.get("ok"):
            return plan
        if plan["source_sha256"] != expected_source_sha256:
            return {
                "ok": False,
                "capability": CAPABILITY,
                "error": "source_hash_mismatch",
                "expected": expected_source_sha256,
                "observed": plan["source_sha256"],
            }
        if plan["target_sha256"] != expected_target_sha256:
            return {
                "ok": False,
                "capability": CAPABILITY,
                "error": "target_hash_mismatch",
                "expected": expected_target_sha256,
                "observed": plan["target_sha256"],
            }
        if not plan["would_change"]:
            result = {**plan, "ok": True, "idempotent": True, "dry_run": dry_run}
            _audit("apply_promotion", result, metadata)
            return result
        if dry_run:
            result = {**plan, "ok": True, "dry_run": True, "would_promote": True}
            _audit("apply_promotion", result, metadata)
            return result

        source = Path(plan["source_path"])
        target = Path(plan["target_path"])
        current_hash = _sha256(target)
        if current_hash != expected_target_sha256:
            return {
                "ok": False,
                "capability": CAPABILITY,
                "error": "target_changed_before_apply",
                "expected": expected_target_sha256,
                "observed": current_hash,
            }
        if _sha256(source) != expected_source_sha256:
            return {
                "ok": False,
                "capability": CAPABILITY,
                "error": "source_changed_before_apply",
            }

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        rel = _safe_relative_path(relative_path)
        backup = (BACKUP_ROOT.expanduser().resolve() / stamp / rel).resolve()
        backup_root = BACKUP_ROOT.expanduser().resolve()
        if backup_root not in backup.parents:
            raise PermissionError("backup_path_escape")
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
        backup_hash = _sha256(backup)
        if backup_hash != expected_target_sha256:
            raise RuntimeError("backup_hash_mismatch")

        temp = target.with_name(f".{target.name}.promote-{secrets.token_hex(6)}.tmp")
        promoted = False
        rolled_back = False
        try:
            shutil.copy2(source, temp)
            if _sha256(temp) != expected_source_sha256:
                raise RuntimeError("staged_source_hash_mismatch")
            os.replace(temp, target)
            promoted = True
            final_hash = _sha256(target)
            if final_hash != expected_source_sha256:
                rollback_temp = target.with_name(f".{target.name}.rollback-{secrets.token_hex(6)}.tmp")
                shutil.copy2(backup, rollback_temp)
                os.replace(rollback_temp, target)
                rolled_back = True
                raise RuntimeError("post_promote_hash_mismatch")
        finally:
            try:
                if temp.exists():
                    temp.unlink()
            except Exception:
                pass

        result = {
            "ok": True,
            "capability": CAPABILITY,
            "dry_run": False,
            "promoted": promoted,
            "rolled_back": rolled_back,
            "relative_path": rel.as_posix(),
            "source_sha256": expected_source_sha256,
            "previous_target_sha256": expected_target_sha256,
            "target_sha256": _sha256(target),
            "backup_path": str(backup),
            "backup_sha256": backup_hash,
            "target_path": str(target),
        }
        _audit("apply_promotion", result, metadata)
        return result
    except Exception as exc:
        result = {"ok": False, "capability": CAPABILITY, "error": str(exc)}
        _audit("apply_promotion", result, metadata)
        return result


def rollback_promotion(
    *,
    project_id: str,
    repo: str,
    relative_path: str,
    backup_path: str,
    expected_current_sha256: str,
    expected_backup_sha256: str,
    approval_id: str,
    actor: str,
    task_id: str,
    correlation_id: str,
    node: str = "primary",
    dry_run: bool = True,
) -> dict[str, Any]:
    metadata = {
        "project_id": project_id,
        "repo": repo,
        "relative_path": relative_path,
        "node": node,
        "actor": actor,
        "task_id": task_id,
        "correlation_id": correlation_id,
    }
    try:
        _require_platform_identity(project_id, repo)
        if not all(str(x or "").strip() for x in (backup_path, expected_current_sha256, expected_backup_sha256, approval_id, actor, task_id, correlation_id)):
            raise ValueError("rollback_preconditions_required")

        approval = _validate_host_approval(
            approval_id=approval_id,
            action="runtime_file_rollback",
            repo=repo,
            project_id=project_id,
            node=node,
        )
        if not approval.get("ok"):
            return {"ok": False, "capability": CAPABILITY, "error": approval.get("error") or "approval_invalid"}

        rel, target = _target_path(relative_path)
        backup_root = BACKUP_ROOT.expanduser().resolve()
        backup = Path(backup_path).expanduser().resolve()
        if backup_root not in backup.parents or not backup.is_file():
            raise PermissionError("backup_not_allowlisted")
        if not target.is_file():
            return {"ok": False, "error": "target_file_missing", "target_path": str(target)}

        current_hash = _sha256(target)
        backup_hash = _sha256(backup)
        if current_hash != expected_current_sha256:
            return {"ok": False, "error": "target_hash_mismatch", "expected": expected_current_sha256, "observed": current_hash}
        if backup_hash != expected_backup_sha256:
            return {"ok": False, "error": "backup_hash_mismatch", "expected": expected_backup_sha256, "observed": backup_hash}
        if dry_run:
            result = {
                "ok": True,
                "dry_run": True,
                "would_rollback": True,
                "relative_path": rel.as_posix(),
                "target_sha256": current_hash,
                "backup_sha256": backup_hash,
            }
            _audit("rollback_promotion", result, metadata)
            return result

        temp = target.with_name(f".{target.name}.rollback-{secrets.token_hex(6)}.tmp")
        try:
            shutil.copy2(backup, temp)
            if _sha256(temp) != expected_backup_sha256:
                raise RuntimeError("staged_backup_hash_mismatch")
            os.replace(temp, target)
        finally:
            try:
                if temp.exists():
                    temp.unlink()
            except Exception:
                pass

        final_hash = _sha256(target)
        result = {
            "ok": final_hash == expected_backup_sha256,
            "capability": CAPABILITY,
            "dry_run": False,
            "rolled_back": final_hash == expected_backup_sha256,
            "relative_path": rel.as_posix(),
            "target_sha256": final_hash,
            "backup_sha256": backup_hash,
            "target_path": str(target),
        }
        _audit("rollback_promotion", result, metadata)
        return result
    except Exception as exc:
        result = {"ok": False, "capability": CAPABILITY, "error": str(exc)}
        _audit("rollback_promotion", result, metadata)
        return result


MAX_PATCH_REPLACEMENTS = 10
MAX_PATCH_BYTES = 100_000


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _detect_line_ending(text: str) -> str:
    crlf = text.count("\r\n")
    lf = text.count("\n")
    bare_lf = lf - crlf
    if crlf and bare_lf:
        raise ValueError("mixed_line_endings")
    return "\r\n" if crlf else "\n"


def _adapt_replacements_to_line_ending(
    replacements: list[dict[str, Any]],
    line_ending: str,
) -> list[dict[str, Any]]:
    adapted = []
    for item in replacements:
        adapted.append(
            {
                **item,
                "before": item["before"].replace("\n", line_ending),
                "after": item["after"].replace("\n", line_ending),
            }
        )
    return adapted


def _normalize_replacements(replacements: Any) -> list[dict[str, Any]]:
    if not isinstance(replacements, list) or not replacements:
        raise ValueError("replacements_required")
    if len(replacements) > MAX_PATCH_REPLACEMENTS:
        raise ValueError("too_many_replacements")
    normalized: list[dict[str, Any]] = []
    total = 0
    for item in replacements:
        if not isinstance(item, dict):
            raise ValueError("replacement_invalid")
        before = str(item.get("before") or "").replace("\r\n", "\n")
        after = str(item.get("after") or "").replace("\r\n", "\n")
        expected_count = int(item.get("expected_count", 1))
        if not before:
            raise ValueError("replacement_before_required")
        if expected_count != 1:
            raise ValueError("replacement_expected_count_must_be_one")
        total += len(before.encode("utf-8")) + len(after.encode("utf-8"))
        if total > MAX_PATCH_BYTES:
            raise ValueError("replacement_payload_too_large")
        normalized.append(
            {
                "before": before,
                "after": after,
                "expected_count": expected_count,
            }
        )
    return normalized


def plan_text_patch(
    *,
    project_id: str,
    repo: str,
    relative_path: str,
    replacements: Any,
    node: str = "primary",
) -> dict[str, Any]:
    try:
        _require_platform_identity(project_id, repo)
        rel, target = _target_path(relative_path)
        if not target.is_file():
            return {"ok": False, "error": "target_file_missing", "target_path": str(target)}
        raw = target.read_bytes()
        original = raw.decode("utf-8")
        line_ending = _detect_line_ending(original)
        ops = _adapt_replacements_to_line_ending(
            _normalize_replacements(replacements),
            line_ending,
        )
        patched = original
        applied = []
        for index, item in enumerate(ops):
            count = patched.count(item["before"])
            if count != item["expected_count"]:
                return {
                    "ok": False,
                    "capability": CAPABILITY,
                    "error": "replacement_match_count_mismatch",
                    "replacement_index": index,
                    "expected_count": item["expected_count"],
                    "observed_count": count,
                }
            patched = patched.replace(item["before"], item["after"], 1)
            applied.append({"index": index, "matched": 1})

        patched_bytes = patched.encode("utf-8")
        current_hash = _bytes_sha256(raw)
        result_hash = _bytes_sha256(patched_bytes)
        return {
            "ok": True,
            "capability": CAPABILITY,
            "project_id": project_id,
            "repo": repo,
            "node": node,
            "relative_path": rel.as_posix(),
            "target_path": str(target),
            "target_sha256": current_hash,
            "result_sha256": result_hash,
            "replacement_count": len(applied),
            "would_change": current_hash != result_hash,
            "target_bytes": len(raw),
            "result_bytes": len(patched_bytes),
            "line_ending": "crlf" if line_ending == "\r\n" else "lf",
        }
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}


def apply_text_patch(
    *,
    project_id: str,
    repo: str,
    relative_path: str,
    replacements: Any,
    expected_target_sha256: str,
    expected_result_sha256: str,
    approval_id: str,
    actor: str,
    task_id: str,
    correlation_id: str,
    node: str = "primary",
    dry_run: bool = True,
) -> dict[str, Any]:
    metadata = {
        "project_id": project_id,
        "repo": repo,
        "relative_path": relative_path,
        "node": node,
        "actor": actor,
        "task_id": task_id,
        "correlation_id": correlation_id,
    }
    try:
        if not all(
            str(x or "").strip()
            for x in (
                expected_target_sha256,
                expected_result_sha256,
                approval_id,
                actor,
                task_id,
                correlation_id,
            )
        ):
            raise ValueError("patch_preconditions_required")

        approval = _validate_host_approval(
            approval_id=approval_id,
            action="runtime_hunk_promote",
            repo=repo,
            project_id=project_id,
            node=node,
        )
        if not approval.get("ok"):
            return {
                "ok": False,
                "capability": CAPABILITY,
                "error": approval.get("error") or "approval_invalid",
            }

        plan = plan_text_patch(
            project_id=project_id,
            repo=repo,
            relative_path=relative_path,
            replacements=replacements,
            node=node,
        )
        if not plan.get("ok"):
            return plan
        if plan["target_sha256"] != expected_target_sha256:
            return {
                "ok": False,
                "capability": CAPABILITY,
                "error": "target_hash_mismatch",
                "expected": expected_target_sha256,
                "observed": plan["target_sha256"],
            }
        if plan["result_sha256"] != expected_result_sha256:
            return {
                "ok": False,
                "capability": CAPABILITY,
                "error": "result_hash_mismatch",
                "expected": expected_result_sha256,
                "observed": plan["result_sha256"],
            }
        if not plan["would_change"]:
            result = {**plan, "ok": True, "idempotent": True, "dry_run": dry_run}
            _audit("apply_text_patch", result, metadata)
            return result
        if dry_run:
            result = {**plan, "ok": True, "dry_run": True, "would_promote": True}
            _audit("apply_text_patch", result, metadata)
            return result

        rel, target = _target_path(relative_path)
        raw = target.read_bytes()
        original = raw.decode("utf-8")
        if _bytes_sha256(raw) != expected_target_sha256:
            return {
                "ok": False,
                "capability": CAPABILITY,
                "error": "target_changed_before_apply",
                "expected": expected_target_sha256,
                "observed": _bytes_sha256(raw),
            }

        line_ending = _detect_line_ending(original)
        patched = original
        ops = _adapt_replacements_to_line_ending(
            _normalize_replacements(replacements),
            line_ending,
        )
        for index, item in enumerate(ops):
            count = patched.count(item["before"])
            if count != 1:
                return {
                    "ok": False,
                    "capability": CAPABILITY,
                    "error": "replacement_match_count_changed",
                    "replacement_index": index,
                    "observed_count": count,
                }
            patched = patched.replace(item["before"], item["after"], 1)
        patched_bytes = patched.encode("utf-8")
        if _bytes_sha256(patched_bytes) != expected_result_sha256:
            return {
                "ok": False,
                "capability": CAPABILITY,
                "error": "planned_result_changed_before_apply",
            }

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_root = BACKUP_ROOT.expanduser().resolve()
        backup = (backup_root / stamp / rel).resolve()
        if backup_root not in backup.parents:
            raise PermissionError("backup_path_escape")
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
        backup_hash = _sha256(backup)
        if backup_hash != expected_target_sha256:
            raise RuntimeError("backup_hash_mismatch")

        temp = target.with_name(f".{target.name}.patch-{secrets.token_hex(6)}.tmp")
        rolled_back = False
        try:
            temp.write_bytes(patched_bytes)
            shutil.copystat(target, temp)
            if _sha256(temp) != expected_result_sha256:
                raise RuntimeError("staged_result_hash_mismatch")
            os.replace(temp, target)
            final_hash = _sha256(target)
            if final_hash != expected_result_sha256:
                rollback_temp = target.with_name(
                    f".{target.name}.rollback-{secrets.token_hex(6)}.tmp"
                )
                shutil.copy2(backup, rollback_temp)
                os.replace(rollback_temp, target)
                rolled_back = True
                raise RuntimeError("post_patch_hash_mismatch")
        finally:
            try:
                if temp.exists():
                    temp.unlink()
            except Exception:
                pass

        result = {
            "ok": True,
            "capability": CAPABILITY,
            "dry_run": False,
            "promoted": True,
            "rolled_back": rolled_back,
            "relative_path": rel.as_posix(),
            "previous_target_sha256": expected_target_sha256,
            "target_sha256": _sha256(target),
            "result_sha256": expected_result_sha256,
            "replacement_count": plan["replacement_count"],
            "backup_path": str(backup),
            "backup_sha256": backup_hash,
            "target_path": str(target),
        }
        _audit("apply_text_patch", result, metadata)
        return result
    except Exception as exc:
        result = {"ok": False, "capability": CAPABILITY, "error": str(exc)}
        _audit("apply_text_patch", result, metadata)
        return result
