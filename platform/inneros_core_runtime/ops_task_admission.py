"""Normalize ops admission so tasks land on the correct execution plane (systemic, not per-task patches)."""

from __future__ import annotations

import re
from typing import Any

DEVICE_FABRIC_MARKERS = (
    "device fabric",
    "device_fabric",
    "entrapass",
    "kantech",
    "bellini iii",
    "bellini iii-iv",
    "bellini i-ii",
    "solo lectura",
    "read-only",
    "read only",
    "preflight",
    "capacidades del device",
    "fabric de dispositivos",
)
IMPLEMENTATION_MARKERS = (
    "implement",
    "implementar",
    "patch",
    "fix ",
    "arreglar",
    "deploy",
    "merge",
    "pull request",
    "refactor",
)


def _haystack(task: dict[str, Any]) -> str:
    parts = [
        str(task.get("title") or ""),
        str(task.get("objective") or ""),
        str(task.get("correlation_id") or ""),
        str((task.get("payload") or {}).get("intent") or ""),
    ]
    return " ".join(parts).lower()


def looks_like_device_fabric_read(task: dict[str, Any]) -> bool:
    text = _haystack(task)
    if not any(marker in text for marker in DEVICE_FABRIC_MARKERS):
        return False
    return not any(marker in text for marker in IMPLEMENTATION_MARKERS)


def normalize_ops_admission(task: dict[str, Any]) -> dict[str, Any]:
    """Apply admission defaults before Temporal/Mongo persist."""
    doc = dict(task)
    if looks_like_device_fabric_read(doc):
        doc["task_class"] = "operational"
        doc["execution_lane"] = "device_fabric"
        doc["runtime_profile"] = doc.get("runtime_profile") or "capability_read"
        doc["execution_policy"] = doc.get("execution_policy") or "read_only"
        doc["assignee"] = str(doc.get("assignee") or "ralfia").lower()
        doc["preferred_provider"] = str(doc.get("preferred_provider") or "ralfia").lower()
        doc["do_not_auto_dispatch"] = True
        payload = dict(doc.get("payload") or {})
        payload["capability_plane"] = "device_fabric"
        payload.setdefault("repo_optional", True)
        doc["payload"] = payload
        doc["admission_normalized"] = "device_fabric_read"
    return doc


def repair_misclassified_task(task: dict[str, Any]) -> dict[str, Any] | None:
    """Return Mongo $set patch when an existing task should be reclassified."""
    if not looks_like_device_fabric_read(task):
        return None
    lane = str(task.get("execution_lane") or "").lower()
    task_class = str(task.get("task_class") or "").lower()
    repo = str(task.get("repo") or task.get("related_project") or "").strip()
    if lane == "device_fabric" and task_class in {"operational", "business_ops"}:
        return None
    if task_class == "coding" and not repo:
        return {
            "task_class": "operational",
            "execution_lane": "device_fabric",
            "runtime_profile": "capability_read",
            "execution_policy": "read_only",
            "do_not_auto_dispatch": True,
            "admission_repair_reason": "device_fabric_read_misclassified_as_coding_without_repo",
        }
    return None
