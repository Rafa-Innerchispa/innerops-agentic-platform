"""Task Intent Classifier and Validation Enforcer for InnerOS Autonomous Tasks.

Provides deterministic classification into:
- coding: Code modifications, bug fixes, features, refactoring, tests.
- review: PR review, diff analysis, code inspection, verdicts.
- research: Investigation, exploration, source discovery, feasibility studies.
- operations: Infrastructure, device fabric, networks, backups, restarts, health checks.
- deployment: Deployments, releases, rollouts, cloud run, service publishing.
- monitoring: Telemetry sweeps, metrics collection, alert observation, heartbeat checks.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

TASK_CLASSES = ("coding", "review", "research", "operations", "deployment", "monitoring")

# Patterns for explicit classification
_REVIEW_PATTERNS = re.compile(
    r"\b(?:review|revisar|revisi[oó]n|verdict|evaluar|audit\s+code|inspect\s+pr|check\s+diff|pr\s+review)\b",
    re.IGNORECASE,
)

_RESEARCH_PATTERNS = re.compile(
    r"\b(?:research|investigar|investigaci[oó]n|explorar|evaluar\s+viabilidad|buscar\s+fuentes|benchmark|discovery|estudio)\b",
    re.IGNORECASE,
)

_DEPLOYMENT_PATTERNS = re.compile(
    r"\b(?:deploy|despliegue|desplegar|release|publicar|rollout|cloud\s+run\s+deploy|publish\s+service|pipeline\s+deploy)\b",
    re.IGNORECASE,
)

_OPERATIONS_PATTERNS = re.compile(
    r"\b(?:operation|operaciones|network|red|device\s+fabric|switch|router|access\s+point|ap|backup|restore|restart|reboot|poe|failover|cleanup|limpieza|infra|dns|gateway|barrido)\b",
    re.IGNORECASE,
)

_MONITORING_PATTERNS = re.compile(
    r"\b(?:monitoring|monitoreo|metrics|m[eé]tricas|telemetr[ií]a|telemetry|alert|alerta|health\s+check|watchdog|liveness)\b",
    re.IGNORECASE,
)

_CODING_PATTERNS = re.compile(
    r"\b(?:coding|code|c[oó]digo|fix|feat|bug|patch|refactor|implement|implementar|crear\s+archivo|modificar|unit\s+test|test\s+suite)\b",
    re.IGNORECASE,
)

# Informational message markers (should not create coding tasks)
_INFORMATIONAL_TYPES = frozenset({"message", "status", "reply", "approval", "event", "informational"})
_TASK_DIRECTIVE_PATTERN = re.compile(
    r"\b(?:INSTRUCCI[ÓO]N|ORDEN|ACTION\s+REQUIRED|TODO|NUEVA\s+TAREA|MANDATO)\b|\b(?:TASK|TAREA)\s*:\s*",
    re.IGNORECASE,
)


def is_informational_message(
    message_type: str = "message",
    title: str = "",
    body: str = "",
    payload: Optional[Dict[str, Any]] = None,
) -> bool:
    """Return True if message is purely informational and should NOT create an ops_task."""
    payload = payload or {}
    if payload.get("auto_create_ops_task") is True or payload.get("requires_ops_task") is True:
        return False
    full_text = f"{title} {body}"
    lower_text = full_text.lower()
    if "[p0]" in lower_text or "[p1]" in lower_text:
        return False
    mtype = str(message_type or "").strip().lower()
    if mtype == "task":
        return False
    if mtype in _INFORMATIONAL_TYPES:
        if not _TASK_DIRECTIVE_PATTERN.search(full_text):
            return True
    return False


def classify_task_intent(
    title: str = "",
    body: str = "",
    checklist: Optional[List[str]] = None,
    payload: Optional[Dict[str, Any]] = None,
    explicit_class: Optional[str] = None,
) -> str:
    """Deterministic classification of a task into one of the 6 canonical task_classes."""
    payload = payload or {}
    exp = (explicit_class or payload.get("task_class") or "").strip().lower()
    if exp in TASK_CLASSES:
        return exp

    checklist_text = " ".join(str(item) for item in (checklist or []))
    combined_text = f"{title} {body} {checklist_text}".lower()

    # Review takes precedence if explicitly indicated in title/text
    if _REVIEW_PATTERNS.search(title) or (_REVIEW_PATTERNS.search(combined_text) and not ("fix" in title.lower() or "implement" in title.lower())):
        return "review"
    if _RESEARCH_PATTERNS.search(title) or (_RESEARCH_PATTERNS.search(combined_text) and not ("fix" in title.lower() or "implement" in title.lower())):
        return "research"
    if _DEPLOYMENT_PATTERNS.search(title) or _DEPLOYMENT_PATTERNS.search(combined_text):
        return "deployment"
    if _OPERATIONS_PATTERNS.search(title) or (_OPERATIONS_PATTERNS.search(combined_text) and not ("fix" in title.lower() or "implement" in title.lower())):
        return "operations"
    if _MONITORING_PATTERNS.search(title) or (_MONITORING_PATTERNS.search(combined_text) and not ("fix" in title.lower() or "implement" in title.lower())):
        return "monitoring"
    if _CODING_PATTERNS.search(combined_text):
        return "coding"

    return "coding" if ("fix" in combined_text or "feat" in combined_text or "add" in combined_text) else "operations"


def validate_coding_bindings(
    repo: Optional[str] = None,
    project_id: Optional[str] = None,
    related_project: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Optional[str]]:
    """Verify that a coding task has mandatory repo/project bindings."""
    payload = payload or {}
    has_repo = bool(
        (repo and str(repo).strip())
        or (project_id and str(project_id).strip())
        or (related_project and str(related_project).strip())
        or (payload.get("repo") and str(payload.get("repo")).strip())
        or (payload.get("project_id") and str(payload.get("project_id")).strip())
        or (payload.get("related_project") and str(payload.get("related_project")).strip())
    )
    if not has_repo:
        return False, "missing_repo_binding: coding tasks require explicit repo, project_id, or related_project"
    return True, None
