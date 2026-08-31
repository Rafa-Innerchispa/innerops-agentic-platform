"""Bounded scheduler task contract: read-only vs product-write and repo truth."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

READ_ONLY_MODES = frozenset(
    {"read_only", "readonly", "verify", "qa", "review", "audit", "inspect", "evidence_only"}
)
READ_ONLY_MARKERS = (
    "read-only",
    "read only",
    "readonly",
    "solo lectura",
    "verify only",
    "qa only",
    "review only",
    "audit only",
    "no source edits",
    "no source write",
    "no editar",
    "sin editar",
    "inspección solamente",
    "inspeccion solamente",
    "evidence-only",
    "evidence only",
    "no deploy",
    "no restart",
    "read only / no source",
    "no modificar judge",
    "no modificar scheduler",
)
DEV_TASK_TERMS = (
    "implement",
    "build",
    "code",
    "feature",
    "module",
    "frontend",
    "runtime",
    "gateway",
    "contract",
    "adapter",
    "api",
    "test",
    "tests",
    "fix",
    "repair",
    "debug",
    "refactor",
    "regression",
    "scheduler",
    "worker",
    "verifier",
    "crear",
    "implementar",
    "construir",
    "codigo",
    "modulo",
    "contrato",
    "corregir",
    "arreglar",
    "reparar",
    "desarrollar",
    "programar",
    "prueba",
    "validar",
)
DOCS_TASK_TERMS = ("docs-only", "documentation only", "documentacion", "documentación", "readme", "runbook")
EXPLICIT_REPO_RE = re.compile(
    r"\b(?:repo|repository|repositorio)\s+(?:expl[ií]cito|explicit|only)\s*[:=]\s*"
    r"(Rafa-Innerchispa/[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*)",
    flags=re.IGNORECASE,
)
REPO_ONLY_RE = re.compile(
    r"\bRepo\s+ONLY\s*:\s*(Rafa-Innerchispa/[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*)",
    flags=re.IGNORECASE,
)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def task_search_text(task: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("title", "correlation_id", "related_project", "project", "kind", "source"):
        parts.append(str(task.get(key) or ""))
    payload = task.get("payload")
    if isinstance(payload, dict):
        for key in ("repo", "repository", "related_project", "project", "task_id", "kind", "source"):
            parts.append(str(payload.get(key) or ""))
    parts.extend(str(item) for item in task.get("checklist") or [])
    parts.extend(str(item) for item in task.get("tags") or [])
    return " ".join(parts).lower()


def task_mode(task: dict[str, Any]) -> str:
    explicit = str(task.get("task_mode") or task.get("execution_mode") or "").strip().lower().replace("-", "_")
    if explicit in READ_ONLY_MODES:
        return "read_only"
    if task.get("read_only") is True or task.get("dev_swarm_read_only") is True:
        return "read_only"
    if task.get("allow_source_writes") is False:
        return "read_only"
    text = task_search_text(task)
    if any(marker in text for marker in READ_ONLY_MARKERS):
        return "read_only"
    return "product_write"


def is_read_only_task(task: dict[str, Any]) -> bool:
    return task_mode(task) == "read_only"


def is_docs_only_objective(objective: str) -> bool:
    text = (objective or "").lower()
    return any(term in text for term in DOCS_TASK_TERMS) and not any(term in text for term in DEV_TASK_TERMS)


def requires_product_writes(objective: str, task: dict[str, Any] | None = None) -> bool:
    if task and is_read_only_task(task):
        return False
    if is_docs_only_objective(objective):
        return False
    return any(term in (objective or "").lower() for term in DEV_TASK_TERMS)


def explicit_repo_from_labels(task: dict[str, Any], *, canonical_hints: dict[str, str]) -> str | None:
    raw_parts = [str(task.get("title") or ""), *[str(item) for item in task.get("checklist") or []]]
    raw_text = " ".join(raw_parts)
    for pattern in (EXPLICIT_REPO_RE, REPO_ONLY_RE):
        match = pattern.search(raw_text)
        if not match:
            continue
        full = match.group(1)
        repo_name = full.split("/", 1)[1]
        for marker, repo in canonical_hints.items():
            if marker == repo_name.lower():
                return repo
        return full
    return None


def repo_route_mismatch(*, worker_repo: str | None, expected_repo: str | None) -> bool:
    worker = str(worker_repo or "").strip()
    expected = str(expected_repo or "").strip()
    if not worker or not expected:
        return False
    return worker != expected


def ops_liveness_expired(task: dict[str, Any], *, stale_seconds: int, now: datetime | None = None) -> bool:
    current = now or datetime.now(timezone.utc)
    status = str(task.get("status") or "").lower()
    if status not in {"accepted", "in_progress", "verification"}:
        return False
    if task.get("worker_token") or task.get("execution_token"):
        heartbeat = _parse_ts(task.get("last_heartbeat_at"))
        if heartbeat and (current.timestamp() - heartbeat.timestamp()) <= stale_seconds:
            return False
        started = _parse_ts(task.get("started_at") or task.get("accepted_at"))
        if started and (current.timestamp() - started.timestamp()) <= stale_seconds:
            return False
        return True
    heartbeat = _parse_ts(task.get("last_heartbeat_at"))
    if heartbeat:
        return (current.timestamp() - heartbeat.timestamp()) > stale_seconds
    started = _parse_ts(task.get("started_at") or task.get("accepted_at") or task.get("updated_at"))
    if not started:
        return status == "in_progress"
    return (current.timestamp() - started.timestamp()) > stale_seconds
