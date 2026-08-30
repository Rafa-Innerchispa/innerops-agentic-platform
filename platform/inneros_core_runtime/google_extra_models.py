"""Governed Google AI model lanes for InnerOS Resource Fabric.

This module keeps optional Google-hosted model use explicit, allowlisted and
cheap. Local AMD/Intel lanes remain the default; these lanes are for hackathon
evidence, critical review, low-cost triage and semantic memory retrieval.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from google.oauth2.credentials import Credentials

PROVIDER_ID = "google-ai-platform"
DEFAULT_PROJECT_ID = "innerops-agentic-platform"
DEFAULT_LOCATION = "us-central1"
SMOKE_MAX_PROMPT_CHARS = 512
SMOKE_MAX_OUTPUT_TOKENS = 32
GCLOUD_TIMEOUT_SECONDS = int(os.getenv("INNEROS_GCLOUD_TIMEOUT_SECONDS", "30"))


@dataclass(frozen=True)
class GoogleModelLane:
    lane_id: str
    model_ref: str
    modality: str
    task_classes: tuple[str, ...]
    role: str
    priority: int
    cost_policy: str
    default_enabled: bool = True
    dimensions: int | None = None
    preferred_location: str = ""
    availability_note: str = ""

    def as_model_provider(self) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "model_provider": self.lane_id,
            "provider_id": PROVIDER_ID,
            "model_ref": self.model_ref,
            "task_classes": list(self.task_classes),
            "role": self.role,
            "priority": self.priority,
            "cost_policy": self.cost_policy,
            "default_enabled": self.default_enabled,
            "governance": "allowlisted model id; live smoke requires allow_live; low token/output limits",
        }
        if self.dimensions is not None:
            doc["dimensions"] = self.dimensions
        if self.preferred_location:
            doc["preferred_location"] = self.preferred_location
        if self.availability_note:
            doc["availability_note"] = self.availability_note
        return doc


LANES: tuple[GoogleModelLane, ...] = (
    GoogleModelLane(
        lane_id="google-gemini-primary",
        model_ref=os.getenv("INNEROS_GEMINI_MODEL", "gemini-2.5-flash"),
        modality="text",
        task_classes=("agentic_reasoning", "cloud_reasoning", "critical_review"),
        role="Primary Google reasoning path when local-first routing escalates to Google.",
        priority=30,
        cost_policy="strategic_cloud",
    ),
    GoogleModelLane(
        lane_id="google-flash-lite-triage",
        model_ref=os.getenv("INNEROS_GOOGLE_TRIAGE_MODEL", "gemini-2.5-flash-lite"),
        modality="text",
        task_classes=("classification", "triage", "bounded_reasoning", "high_volume_review"),
        role="Low-cost classification and triage before any expensive reasoning path.",
        priority=25,
        cost_policy="bounded_low_cost",
    ),
    GoogleModelLane(
        lane_id="google-memory-embedding",
        model_ref=os.getenv("INNEROS_GOOGLE_EMBEDDING_MODEL", "gemini-embedding-001"),
        modality="embedding",
        task_classes=("memory_embedding", "semantic_retrieval", "document_retrieval"),
        role="Semantic Memory/Document Vault retrieval vectors; no generative output.",
        priority=26,
        cost_policy="bounded_low_cost",
        dimensions=3072,
    ),
    GoogleModelLane(
        lane_id="google-gemini-35-bounded-review",
        model_ref=os.getenv("INNEROS_GOOGLE_REVIEW_MODEL", "gemini-3.5-flash-lite"),
        modality="text",
        task_classes=("critical_review", "low_cost_review", "bounded_reasoning"),
        role="Available Google preview reviewer lane for hackathon/product evidence while Gemma access is unavailable.",
        priority=34,
        cost_policy="bounded_low_cost_preview",
        preferred_location="global",
        availability_note="Live smoke passed through Vertex global on 2026-08-29.",
    ),
    GoogleModelLane(
        lane_id="google-gemma-bounded-review",
        model_ref=os.getenv("INNEROS_GOOGLE_GEMMA_MODEL", "gemma-3-27b-it"),
        modality="text",
        task_classes=("gemma_review", "low_cost_review", "bounded_reasoning"),
        role="Gemma specialist critic/reviewer when Google exposes the model to this project.",
        priority=35,
        cost_policy="blocked_until_live_access",
        default_enabled=False,
        availability_note="Vertex returned 404 for Gemma IDs in us-central1/global on 2026-08-29; keep lane explicit, not PASS.",
    ),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_id(project_id: str = "") -> str:
    return (project_id or os.getenv("GOOGLE_CLOUD_PROJECT") or DEFAULT_PROJECT_ID).strip()


def _location(location: str = "") -> str:
    return (location or os.getenv("INNEROS_GOOGLE_MODEL_LOCATION") or DEFAULT_LOCATION).strip()


def _lane_location(lane: GoogleModelLane, location: str = "") -> str:
    return (location or lane.preferred_location or os.getenv("INNEROS_GOOGLE_MODEL_LOCATION") or DEFAULT_LOCATION).strip()


def _gcloud_bin() -> str:
    for candidate in (
        os.getenv("GCLOUD_BIN", ""),
        shutil.which("gcloud") or "",
        "/home/rlopez/.local/bin/gcloud",
        "/snap/bin/gcloud",
    ):
        if candidate and os.path.exists(candidate):
            return candidate
    return "gcloud"


def _oauth_token() -> str:
    proc = subprocess.run([_gcloud_bin(), "auth", "print-access-token"], capture_output=True, text=True, timeout=GCLOUD_TIMEOUT_SECONDS)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError((proc.stderr or proc.stdout or "gcloud auth print-access-token failed")[:240])
    return proc.stdout.strip()


def _run_gcloud(args: list[str], *, project_id: str = "", timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    project = _project_id(project_id)
    command = [
        _gcloud_bin(),
        *args,
        "--project",
        project,
        "--billing-project",
        project,
    ]
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout or GCLOUD_TIMEOUT_SECONDS)


def get_lane(lane_id: str) -> GoogleModelLane | None:
    key = (lane_id or "").strip()
    return next((lane for lane in LANES if lane.lane_id == key), None)


def allowlist() -> dict[str, Any]:
    lanes = [lane.as_model_provider() for lane in LANES]
    return {
        "ok": True,
        "provider_id": PROVIDER_ID,
        "allowed_models": sorted({lane.model_ref for lane in LANES}),
        "allowed_lanes": lanes,
        "lanes": lanes,
        "smoke_limits": {"max_prompt_chars": SMOKE_MAX_PROMPT_CHARS, "max_output_tokens": SMOKE_MAX_OUTPUT_TOKENS},
        "default_auth_mode": "vertex_oauth_gcloud",
        "gcloud_timeout_seconds": GCLOUD_TIMEOUT_SECONDS,
        "local_first": True,
    }


def model_garden_gemma_preflight(*, project_id: str = "", model_filter: str = "gemma", limit: int = 20, allow_live: bool = False) -> dict[str, Any]:
    """List Gemma Model Garden availability without deploying endpoints."""

    if not allow_live:
        return {
            "ok": True,
            "dry_run": True,
            "command": "gcloud ai model-garden models list --model-filter=<filter> --project=<project> --billing-project=<project>",
            "note": "set allow_live=true to query Vertex Model Garden; this is read-only and does not deploy resources",
        }
    clean_filter = (model_filter or "gemma").strip()[:64]
    clean_limit = max(1, min(int(limit or 20), 50))
    project = _project_id(project_id)
    try:
        proc = _run_gcloud(
            [
                "ai",
                "model-garden",
                "models",
                "list",
                "--model-filter",
                clean_filter,
                "--limit",
                str(clean_limit),
                "--format",
                "json",
            ],
            project_id=project,
            timeout=max(GCLOUD_TIMEOUT_SECONDS, 45),
        )
    except Exception as exc:
        return {
            "ok": False,
            "error": type(exc).__name__,
            "message": str(exc)[:480],
            "project_id": project,
            "model_filter": clean_filter,
            "not_pass": True,
            "ts": _now(),
        }
    import json

    models: list[dict[str, Any]] = []
    if proc.returncode == 0 and proc.stdout.strip():
        try:
            raw_models = json.loads(proc.stdout)
            for item in raw_models if isinstance(raw_models, list) else []:
                deploy = (item.get("supportedActions") or {}).get("deploy") or {}
                multi = (item.get("supportedActions") or {}).get("multiDeployVertex") or {}
                options = []
                if deploy:
                    options.append(deploy)
                options.extend(multi.get("multiDeployVertex") or [])
                deployable = []
                for option in options:
                    machine = ((option.get("dedicatedResources") or {}).get("machineSpec") or {})
                    deployable.append(
                        {
                            "model_display_name": option.get("modelDisplayName"),
                            "machine_type": machine.get("machineType"),
                            "accelerator_type": machine.get("acceleratorType"),
                            "accelerator_count": machine.get("acceleratorCount"),
                            "predict_route": (option.get("containerSpec") or {}).get("predictRoute"),
                        }
                    )
                models.append(
                    {
                        "name": item.get("name"),
                        "version_id": item.get("versionId"),
                        "launch_stage": item.get("launchStage"),
                        "open_source_category": item.get("openSourceCategory"),
                        "can_deploy": bool(deployable),
                        "deployment_options": deployable[:6],
                    }
                )
        except Exception as exc:
            return {
                "ok": False,
                "error": "model_garden_parse_failed",
                "message": str(exc)[:480],
                "stdout_preview": proc.stdout[:1000],
                "stderr_preview": proc.stderr[:1000],
                "project_id": project,
                "not_pass": True,
                "ts": _now(),
            }
    return {
        "ok": proc.returncode == 0,
        "project_id": project,
        "model_filter": clean_filter,
        "count": len(models),
        "models": models,
        "stderr_preview": proc.stderr[:1000],
        "read_only": True,
        "deploy_started": False,
        "cost_guard": "read-only Model Garden list; endpoint deploy requires separate approval",
        "ts": _now(),
    }


def resource_provider_document() -> dict[str, Any]:
    return {
        "provider_id": PROVIDER_ID,
        "label": "Google AI Platform governed lanes",
        "kind": "cloud_model_provider",
        "capabilities": ["agentic_reasoning", "classification", "semantic_retrieval", "embeddings", "critical_review"],
        "local_first": False,
        "status": "configured",
        "project_id": _project_id(),
        "location": _location(),
        "cost_policy": "explicit_cloud_lane_only",
        "governance": "model allowlist + small smoke limits + no production default switch",
    }


def model_provider_documents() -> list[dict[str, Any]]:
    return [lane.as_model_provider() for lane in LANES]


def lanes_status(*, project_id: str = "", location: str = "", live_probe: bool = False) -> dict[str, Any]:
    rows = []
    for lane in LANES:
        row = lane.as_model_provider()
        row.update({"modality": lane.modality, "project_id": _project_id(project_id), "location": _lane_location(lane, location)})
        if live_probe:
            row["smoke"] = smoke_lane(lane.lane_id, project_id=project_id, location=location, allow_live=True)
        rows.append(row)
    return {
        "ok": True,
        "provider": resource_provider_document(),
        "lanes": rows,
        "live_probe": live_probe,
        "cost_guard": {"allow_live_required": True, "max_prompt_chars": SMOKE_MAX_PROMPT_CHARS, "max_output_tokens": SMOKE_MAX_OUTPUT_TOKENS},
    }


def _client(project_id: str, location: str) -> Any:
    from google import genai  # type: ignore

    token = _oauth_token()
    return genai.Client(vertexai=True, project=project_id, location=location, credentials=Credentials(token, quota_project_id=project_id))


def smoke_lane(lane_id: str, *, project_id: str = "", location: str = "", prompt: str = "Reply exactly: ok", allow_live: bool = False) -> dict[str, Any]:
    lane = get_lane(lane_id)
    if lane is None:
        return {"ok": False, "error": "unknown_lane", "known_lanes": [item.lane_id for item in LANES]}
    if not allow_live:
        return {"ok": True, "dry_run": True, "lane": lane.as_model_provider(), "note": "set allow_live=true for a bounded live smoke"}
    clean_prompt = (prompt or "Reply exactly: ok")[:SMOKE_MAX_PROMPT_CHARS]
    project = _project_id(project_id)
    loc = _lane_location(lane, location)
    try:
        client = _client(project, loc)
        if lane.modality == "embedding":
            result = client.models.embed_content(model=lane.model_ref, contents=clean_prompt)
            values = result.embeddings[0].values if getattr(result, "embeddings", None) else []
            return {
                "ok": True,
                "lane_id": lane.lane_id,
                "model": lane.model_ref,
                "modality": lane.modality,
                "project_id": project,
                "location": loc,
                "embedding_dimensions": len(values),
                "live_mode": "LIVE",
                "cost_guard": {"prompt_chars": len(clean_prompt), "max_output_tokens": 0},
                "ts": _now(),
            }
        from google.genai import types  # type: ignore

        response = client.models.generate_content(
            model=lane.model_ref,
            contents=clean_prompt,
            config=types.GenerateContentConfig(max_output_tokens=SMOKE_MAX_OUTPUT_TOKENS),
        )
        return {
            "ok": True,
            "lane_id": lane.lane_id,
            "model": lane.model_ref,
            "modality": lane.modality,
            "project_id": project,
            "location": loc,
            "text_preview": (response.text or "")[:80],
            "live_mode": "LIVE",
            "cost_guard": {"prompt_chars": len(clean_prompt), "max_output_tokens": SMOKE_MAX_OUTPUT_TOKENS},
            "ts": _now(),
        }
    except Exception as exc:
        return {
            "ok": False,
            "lane_id": lane.lane_id,
            "model": lane.model_ref,
            "modality": lane.modality,
            "project_id": project,
            "location": loc,
            "error": type(exc).__name__,
            "message": str(exc)[:360],
            "live_mode": "UNAVAILABLE",
            "not_pass": True,
            "ts": _now(),
        }
