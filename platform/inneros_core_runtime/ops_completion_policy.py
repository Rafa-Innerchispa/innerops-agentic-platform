"""When Git commit / objective files are required for ops completion."""

from __future__ import annotations

from typing import Any

_READ_ONLY_CLASSES = frozenset(
    {
        "verification",
        "read_only",
        "network_diagnostics",
        "investigation",
        "consultation",
        "audit",
    }
)
_CODING_CLASSES = frozenset({"coding", "integration", "implementation", "repair", "feature"})


def _txt(task: dict[str, Any]) -> str:
    return " ".join(
        str(task.get(k) or "")
        for k in ("task_class", "execution_policy", "objective", "title")
    ).lower()


def requires_git_repository(task: dict[str, Any]) -> bool:
    if str(task.get("repo") or task.get("related_project") or "").strip():
        return True
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    return bool(str(payload.get("repo") or "").strip())


def requires_git_commit(task: dict[str, Any]) -> bool:
    tc = str(task.get("task_class") or "").strip().lower()
    if tc in _READ_ONLY_CLASSES:
        return False
    if tc in _CODING_CLASSES:
        return True
    text = _txt(task)
    if "read-only" in text or "solo lectura" in text or "rev-parse" in text:
        return False
    if "commit" in text or "pr " in text or "merge" in text:
        return True
    ev_req = task.get("evidence_required") or []
    if isinstance(ev_req, list):
        joined = " ".join(str(x).lower() for x in ev_req)
        if "sha" in joined or "commit" in joined:
            return True
        if "read-only" in joined or "rev-parse" in joined:
            return False
    return requires_git_repository(task) and tc not in _READ_ONLY_CLASSES


def allows_non_commit_completion(task: dict[str, Any], evidence: dict[str, Any] | None) -> bool:
    ev = dict(evidence or {})
    if ev.get("read_only_completion") is True:
        return True
    if str(ev.get("completion_mode") or "") == "read_only_evidence":
        return True
    if not requires_git_commit(task):
        return True
    return False


def validate_completed_evidence(task: dict[str, Any], evidence: dict[str, Any] | None) -> str | None:
    ev = dict(evidence or {})
    if allows_non_commit_completion(task, ev):
        if ev.get("summary") or ev.get("notes") or ev.get("report") or ev.get("test_results"):
            return None
        if ev.get("commit_sha") or ev.get("objective_paths"):
            return None
        return "evidence_required_for_completed: summary/notes/report or git proof"
    sha = str(ev.get("commit_sha") or ev.get("sha") or "").strip()
    if sha:
        return None
    files = int(ev.get("objective_files_count") or 0)
    paths = list(ev.get("objective_paths") or [])
    if files > 0 and paths:
        return None
    tests = ev.get("test_results") or {}
    if tests.get("exit_code") is not None and int(tests.get("exit_code")) == 0:
        return None
    return (
        "evidence_required_for_completed: commit_sha, objective_paths+count, "
        "or test_results.exit_code=0"
    )
