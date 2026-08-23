"""Operational Layer — módulo PC Doctor (visitas, equipos, informes)."""

from raphiia_openai.operational.audit import log_ops_action
from raphiia_openai.operational.constants import (
    COL_AGENT_REGISTRY,
    COL_OPS_AUDIT_LOG,
    PHASE_ACTIVE_COLLECTIONS,
    VISIBILITY_INTERNAL,
    VISIBILITY_LEVELS,
    VISIBILITY_PRIVATE,
)

__all__ = [
    "COL_AGENT_REGISTRY",
    "COL_OPS_AUDIT_LOG",
    "PHASE_ACTIVE_COLLECTIONS",
    "VISIBILITY_INTERNAL",
    "VISIBILITY_LEVELS",
    "VISIBILITY_PRIVATE",
    "log_ops_action",
]
