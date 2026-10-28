"""When Git commit / objective files are required for ops completion."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from inneros_core_runtime.execution_receipts import committed_objective_receipt

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

_TEXT_ONLY_HEADLESS_PRIMARIES = frozenset(
    {
        "antigravity_gemini_api",
        "gemini_api_text_only",
    }
)

_DEPLOYMENT_INTENT_PHRASES = (
    "publish to production",
    "deploy to production",
    "go live",
    "go-live",
    "mutate production host",
    "observed_host_mutation",
    "host mutation required",
    "wordpress publish",
    "cpanel publish",
    "despliegue a producción",
    "publicar en producción",
    "mutate.v1",
)

_DEPLOYMENT_PAYLOAD_ACTIONS = frozenset(
    {"deploy", "publish", "go_live", "mutate_host", "host_mutation", "production_publish"}
)


def _txt(task: dict[str, Any]) -> str:
    return " ".join(
        str(task.get(k) or "")
        for k in ("task_class", "execution_policy", "objective", "title")
    ).lower()


def objective_implies_deployment(task: dict[str, Any]) -> bool:
    """True only when the task structurally requires publishing/mutating production hosts."""
    tc = str(task.get("task_class") or "").strip().lower()
    if tc == "deployment":
        return True
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    action = str(payload.get("action") or payload.get("intent") or "").strip().lower()
    if action in _DEPLOYMENT_PAYLOAD_ACTIONS:
        return True
    if payload.get("deploy") is True or payload.get("publish_to_production") is True:
        return True
    if payload.get("host_mutation_required") is True:
        return True
    ev_req = task.get("evidence_required") or []
    if isinstance(ev_req, list):
        joined = " ".join(str(x).lower() for x in ev_req)
        if "observed_host_mutation" in joined or "host_execution" in joined:
            return True
    text = _txt(task)
    text += " " + " ".join(str(item or "").lower() for item in (task.get("checklist") or []))
    if any(phrase in text for phrase in _DEPLOYMENT_INTENT_PHRASES):
        return True
    lower = text
    if "deploy" in lower or "despliegue" in lower or "publicar" in lower:
        publish_context = (
            "wordpress",
            "cpanel",
            "production",
            "producción",
            "go live",
            "ftp",
            "landing page",
            "sitio web",
        )
        if any(ctx in lower for ctx in publish_context):
            return True
    for item in task.get("checklist") or []:
        item_l = str(item or "").lower()
        if any(m in item_l for m in ("deploy:", "publish:", "go-live", "host mutation")):
            return True
    return False


def is_text_only_headless_evidence(evidence: dict[str, Any] | None) -> bool:
    ev = dict(evidence or {})
    primary = str(ev.get("headless_primary") or "").strip().lower()
    if primary in _TEXT_ONLY_HEADLESS_PRIMARIES:
        return True
    if primary.startswith("antigravity_gemini") and not ev.get("evidence_source"):
        return True
    return False


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


def _deployment_host_evidence_ok(evidence: dict[str, Any]) -> bool:
    ev = dict(evidence or {})
    nested = ev.get("evidence") if isinstance(ev.get("evidence"), dict) else {}
    for root in (ev, nested):
        host = root.get("host_execution") or root.get("deployment_evidence")
        post = root.get("postconditions") or root.get("observed_postconditions")
        if isinstance(host, dict) and host.get("executed") is True:
            if isinstance(post, dict) and post.get("verified") is True:
                return True
    return False


def _verify_paths_on_disk(worktree: Path, paths: list[str]) -> str | None:
    try:
        root = worktree.resolve(strict=True)
    except OSError:
        return "worktree_unavailable"
    for name in paths:
        rel = Path(name)
        if rel.is_absolute() or ".." in rel.parts:
            return f"objective_path_unsafe:{name}"
        full = (root / rel).resolve()
        try:
            full.relative_to(root)
        except ValueError:
            return f"objective_path_outside_worktree:{name}"
        if not full.is_file():
            return f"objective_path_missing_on_disk:{name}"
    return None


def validate_mutating_completion_evidence(
    task: dict[str, Any],
    evidence: dict[str, Any] | None,
    *,
    worktree: Path | None = None,
    before_sha: str = "",
) -> str | None:
    """Fail-closed proof for coding/deployment-style ops completion."""
    ev = dict(evidence or {})
    if is_text_only_headless_evidence(ev):
        return "text_only_headless_executor_cannot_complete"

    if objective_implies_deployment(task) and not _deployment_host_evidence_ok(ev):
        return "deployment_requires_observed_host_mutation"

    sha = str(ev.get("commit_sha") or ev.get("sha") or "").strip()
    paths = [str(p) for p in (ev.get("objective_paths") or []) if str(p).strip()]
    files = int(ev.get("objective_files_count") or 0)
    tests = ev.get("test_results") or {}
    exit_code = tests.get("exit_code")

    if exit_code is None:
        return "evidence_required_for_completed: test_results.exit_code required"
    try:
        exit_int = int(exit_code)
    except (TypeError, ValueError):
        return "evidence_required_for_completed: invalid test_results.exit_code"
    if exit_int != 0 or not tests.get("ok", False):
        return "evidence_required_for_completed: tests must pass"

    if not sha or files <= 0 or not paths:
        return (
            "evidence_required_for_completed: commit_sha, objective_paths, "
            "objective_files_count, and passing tests"
        )

    base = str(before_sha or ev.get("git_before_sha") or task.get("git_baseline_sha") or "").strip()
    wt = worktree
    if wt is None:
        wt_path = str(task.get("worktree") or task.get("local_worktree") or ev.get("worktree") or "").strip()
        if wt_path:
            wt = Path(wt_path)

    if not base:
        return "evidence_required_for_completed: git_baseline_sha required"
    if wt is None:
        return "evidence_required_for_completed: worktree required for git receipt"

    proof = committed_objective_receipt(wt, base)
    if not proof.get("ok"):
        return f"committed_objective_receipt_failed:{proof.get('error')}"
    if proof.get("commit_sha") != sha:
        return "commit_sha_not_from_task_worktree"
    actual = set(proof.get("objective_paths") or [])
    if not set(paths).issubset(actual):
        return "objective_paths_not_in_git_diff"
    missing = _verify_paths_on_disk(wt, paths)
    if missing:
        return missing
    return None


def validate_completed_evidence(task: dict[str, Any], evidence: dict[str, Any] | None) -> str | None:
    ev = dict(evidence or {})
    if allows_non_commit_completion(task, ev):
        if ev.get("summary") or ev.get("notes") or ev.get("report") or ev.get("test_results"):
            return None
        if ev.get("commit_sha") or ev.get("objective_paths"):
            return None
        return "evidence_required_for_completed: summary/notes/report or git proof"
    return validate_mutating_completion_evidence(task, ev)


def validate_terminal_completion(task: dict[str, Any], evidence: dict[str, Any] | None) -> dict[str, Any]:
    ev = dict(evidence or {})
    wt_path = str(task.get("worktree") or task.get("local_worktree") or ev.get("worktree") or "").strip()
    base = str(task.get("git_baseline_sha") or ev.get("git_before_sha") or "").strip()
    if allows_non_commit_completion(task, ev):
        err = validate_completed_evidence(task, ev)
    elif requires_git_commit(task):
        err = validate_mutating_completion_evidence(
            task,
            ev,
            worktree=Path(wt_path) if wt_path else None,
            before_sha=base,
        )
    else:
        err = validate_completed_evidence(task, ev)
    if err:
        return {"ok": False, "error": err, "task_id": task.get("task_id")}
    return {"ok": True, "task_id": task.get("task_id")}
