"""Apply structured local-model output to a repo worktree (shared Temporal + Dev Swarm)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from inneros_core_runtime import local_execution_plane as lep


def _rewrite_path_for_worktree(worktree: Path, raw_path: str) -> str:
    """InnerOS worktrees are often the platform tree at repo root (tests/, not platform/tests/)."""
    rel = str(raw_path or "").strip().replace("\\", "/").lstrip("/")
    if rel.startswith("platform/") and not (worktree / "platform").is_dir():
        if (worktree / "tests").is_dir() or (worktree / "inneros_core_runtime").is_dir():
            return rel.split("platform/", 1)[1]
    return rel


def apply_candidate_response(
    envelope_dict: dict[str, Any],
    worktree: Path,
    *,
    model_text: str,
    actor: str = "temporal_bounded",
) -> dict[str, Any]:
    """Parse JSON file payloads from model text and write via allowlisted LEP."""
    from inneros_core_runtime import dev_swarm_scheduler as dss

    task_id = str(envelope_dict.get("task_id") or "")
    repo = str(envelope_dict.get("repo") or "").strip()
    objective = str(envelope_dict.get("objective") or envelope_dict.get("title") or "")
    work_branch = str(envelope_dict.get("work_branch") or "").strip()
    if not work_branch:
        from inneros_core_runtime import temporal_bounded_executor as tbe

        work_branch = tbe.default_work_branch(envelope_dict)
    correlation_id = str(envelope_dict.get("correlation_id") or task_id)

    payload = dss._fanout_parse_model_json(model_text)
    if isinstance(payload, dict) and isinstance(payload.get("files"), list):
        for item in payload["files"]:
            if isinstance(item, dict) and item.get("path"):
                item["path"] = _rewrite_path_for_worktree(worktree, str(item["path"]))
    files, rejected = dss._safe_generated_files(
        payload, objective, task_id, repo, worktree, model_text=model_text
    )
    files = dss._merge_node_scaffold(
        objective=objective, task_id=task_id, worktree=worktree, files=files, repo=repo
    )
    if not files:
        return {
            "ok": False,
            "error": "model_output_non_actionable",
            "rejected_files": rejected,
            "parsed_payload": bool(payload),
        }

    writes: list[dict[str, Any]] = []
    touched: list[str] = []
    for item in files:
        rel = item["path"]
        content = item["content"]
        result = lep.write_file(
            repo=repo,
            work_branch=work_branch,
            path=rel,
            content=content,
            actor=actor,
            task_id=task_id,
            correlation_id=correlation_id,
            idempotency_key=f"temporal-bounded-write-{task_id}-{rel}",
        )
        ok = bool(result.get("ok"))
        writes.append({"path": rel, "ok": ok, "result": result})
        if ok:
            touched.append(rel)

    return {
        "ok": bool(touched) and all(w["ok"] for w in writes),
        "writes": writes,
        "files_touched": touched,
        "rejected_files": rejected,
        "write_count": len(writes),
    }
