"""Google Gemini runtime adapter for InnerOS/ARIA.

This module makes Gemini a first-class *provider* behind the same InnerOS control
plane used by local models. Gemini can reason and request bounded function calls,
but InnerOS remains responsible for authorization, tool execution, persistence,
verification and evidence.

The module intentionally imports google-genai lazily so the core runtime remains
bootable on local nodes where the Google SDK is not installed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

PROVIDER_ID = "google-gemini-vertex"
MODEL_ID = "gemini-3.5-flash"
DEFAULT_PROJECT_ID = "innerops-agentic-platform"
# Gemini 3.5 Flash PayGo is served through global/us/eu endpoints. Agent Runtime
# can remain in us-central1 while model calls use the US multi-region endpoint.
DEFAULT_MODEL_LOCATION = "us"
DEFAULT_AGENT_LOCATION = "us-central1"


class GeminiRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class GeminiRuntimeConfig:
    project_id: str = DEFAULT_PROJECT_ID
    model: str = MODEL_ID
    model_location: str = DEFAULT_MODEL_LOCATION
    agent_location: str = DEFAULT_AGENT_LOCATION
    store_interactions: bool = True

    @classmethod
    def from_env(cls) -> "GeminiRuntimeConfig":
        return cls(
            project_id=(os.getenv("GOOGLE_CLOUD_PROJECT") or DEFAULT_PROJECT_ID).strip(),
            model=(os.getenv("INNEROS_GEMINI_MODEL") or MODEL_ID).strip(),
            model_location=(os.getenv("INNEROS_GEMINI_MODEL_LOCATION") or DEFAULT_MODEL_LOCATION).strip(),
            agent_location=(os.getenv("INNEROS_AGENT_LOCATION") or DEFAULT_AGENT_LOCATION).strip(),
            store_interactions=(os.getenv("INNEROS_GEMINI_STORE", "true").strip().lower() not in {"0", "false", "no"}),
        )


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    risk_level: str = "low"
    approval_required: bool = False

    def as_interactions_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, (list, tuple)):
        return [_safe_dump(item) for item in value]
    return value


def validate_tool_specs(tools: Iterable[ToolSpec] | None) -> list[ToolSpec]:
    seen: set[str] = set()
    result: list[ToolSpec] = []
    for tool in tools or []:
        if not isinstance(tool, ToolSpec):
            raise GeminiRuntimeError("invalid_tool_spec", "Gemini tools must be ToolSpec instances")
        name = tool.name.strip()
        if not name or name in seen:
            raise GeminiRuntimeError("invalid_tool_name", "Gemini tool names must be unique and non-empty")
        if tool.risk_level not in {"low", "medium", "high", "destructive"}:
            raise GeminiRuntimeError("invalid_tool_risk", f"Unsupported risk level for {name}")
        seen.add(name)
        result.append(tool)
    return result


def resource_provider_document() -> dict[str, Any]:
    cfg = GeminiRuntimeConfig.from_env()
    return {
        "provider_id": PROVIDER_ID,
        "label": "Google Gemini / Vertex AI",
        "kind": "cloud_agent_runtime",
        "capabilities": [
            "agentic_reasoning",
            "coding",
            "critical_review",
            "external_research",
            "multimodal",
            "tool_use",
            "long_context",
            "agent_runtime",
            "memory_bank",
        ],
        "local_first": False,
        "status": "configured",
        "project_id": cfg.project_id,
        "model": cfg.model,
        "model_location": cfg.model_location,
        "agent_location": cfg.agent_location,
        "cost_policy": "strategic_cloud",
        "governance": "InnerOS bounded tools + approval + evidence; Google IAM/Model Armor on cloud path",
    }


def model_provider_document() -> dict[str, Any]:
    cfg = GeminiRuntimeConfig.from_env()
    return {
        "model_provider": "google-gemini",
        "provider_id": PROVIDER_ID,
        "model_ref": cfg.model,
        "task_classes": [
            "agentic_workflow",
            "architecture_complex",
            "critical_review",
            "external_research",
            "vision_ocr",
            "cloud_reasoning",
        ],
        "priority": 30,
        "cost_policy": "strategic_cloud",
    }


def sdk_status() -> dict[str, Any]:
    try:
        from google import genai  # type: ignore

        version = getattr(genai, "__version__", None)
        return {"ok": True, "sdk": "google-genai", "version": version}
    except Exception as exc:
        return {"ok": False, "sdk": "google-genai", "error": type(exc).__name__}


class GeminiInteractionsClient:
    """Thin wrapper around google-genai Interactions API on Vertex AI."""

    def __init__(self, config: GeminiRuntimeConfig | None = None, client: Any | None = None):
        self.config = config or GeminiRuntimeConfig.from_env()
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from google import genai  # type: ignore
        except Exception as exc:
            raise GeminiRuntimeError(
                "google_genai_missing",
                "google-genai is required for live Gemini execution",
                {"install": "google-genai>=2.0.0", "cause": type(exc).__name__},
            ) from exc
        self._client = genai.Client(
            vertexai=True,
            project=self.config.project_id,
            location=self.config.model_location,
        )
        return self._client

    def create_interaction(
        self,
        *,
        prompt: str,
        tools: Iterable[ToolSpec] | None = None,
        previous_interaction_id: str | None = None,
        store: bool | None = None,
    ) -> dict[str, Any]:
        tool_specs = validate_tool_specs(tools)
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "input": prompt,
            "tools": [tool.as_interactions_tool() for tool in tool_specs],
            "store": self.config.store_interactions if store is None else bool(store),
        }
        if previous_interaction_id:
            kwargs["previous_interaction_id"] = previous_interaction_id

        interaction = self._get_client().interactions.create(**kwargs)
        steps = [_safe_dump(step) for step in (getattr(interaction, "steps", None) or [])]
        function_calls = [step for step in steps if isinstance(step, dict) and step.get("type") == "function_call"]
        return {
            "ok": True,
            "provider_id": PROVIDER_ID,
            "model": self.config.model,
            "interaction_id": getattr(interaction, "id", None),
            "output_text": getattr(interaction, "output_text", "") or "",
            "steps": steps,
            "function_calls": function_calls,
        }

    def continue_with_tool_result(
        self,
        *,
        previous_interaction_id: str,
        call_id: str,
        tool_name: str,
        result: Any,
        tools: Iterable[ToolSpec] | None = None,
    ) -> dict[str, Any]:
        if not previous_interaction_id or not call_id or not tool_name:
            raise GeminiRuntimeError("tool_result_context_required", "interaction id, call id and tool name are required")
        tool_specs = validate_tool_specs(tools)
        interaction = self._get_client().interactions.create(
            model=self.config.model,
            previous_interaction_id=previous_interaction_id,
            tools=[tool.as_interactions_tool() for tool in tool_specs],
            input=[
                {
                    "type": "function_result",
                    "name": tool_name,
                    "call_id": call_id,
                    "result": [{"type": "text", "text": str(result)}],
                }
            ],
            store=self.config.store_interactions,
        )
        steps = [_safe_dump(step) for step in (getattr(interaction, "steps", None) or [])]
        return {
            "ok": True,
            "provider_id": PROVIDER_ID,
            "model": self.config.model,
            "interaction_id": getattr(interaction, "id", None),
            "output_text": getattr(interaction, "output_text", "") or "",
            "steps": steps,
        }


class InnerOSGeminiRuntime:
    """Governed Gemini provider used by ARIA routing.

    The caller must explicitly permit external execution. Tool execution remains
    outside this class so the existing InnerOS tool/approval layer stays authoritative.
    """

    def __init__(
        self,
        client: GeminiInteractionsClient | None = None,
        evidence_sink: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.client = client or GeminiInteractionsClient()
        self.evidence_sink = evidence_sink

    def run(
        self,
        *,
        prompt: str,
        correlation_id: str,
        tools: Iterable[ToolSpec] | None = None,
        allow_external: bool = False,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not allow_external:
            return {
                "ok": False,
                "error": "external_execution_not_authorized",
                "provider_id": PROVIDER_ID,
                "correlation_id": correlation_id,
            }
        if not correlation_id.strip():
            raise GeminiRuntimeError("correlation_id_required", "Every Gemini run requires a correlation id")
        tool_specs = validate_tool_specs(tools)
        result = self.client.create_interaction(prompt=prompt, tools=tool_specs)
        evidence = {
            "ts": _now(),
            "event": "gemini_interaction",
            "provider_id": PROVIDER_ID,
            "model": result.get("model"),
            "correlation_id": correlation_id,
            "interaction_id": result.get("interaction_id"),
            "requested_tools": [tool.name for tool in tool_specs],
            "requested_tool_risks": {tool.name: tool.risk_level for tool in tool_specs},
            "function_calls": result.get("function_calls", []),
            "context_keys": sorted((context or {}).keys()),
            "verified": False,
        }
        if self.evidence_sink:
            self.evidence_sink(evidence)
        return {**result, "correlation_id": correlation_id, "evidence": evidence}


def runtime_status() -> dict[str, Any]:
    cfg = GeminiRuntimeConfig.from_env()
    return {
        "ok": True,
        "provider": resource_provider_document(),
        "sdk": sdk_status(),
        "config": {
            "project_id": cfg.project_id,
            "model": cfg.model,
            "model_location": cfg.model_location,
            "agent_location": cfg.agent_location,
            "store_interactions": cfg.store_interactions,
        },
        "security_note": "Gemini proposes function calls; InnerOS executes only bounded approved tools.",
    }
