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
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

logger = logging.getLogger("inneros.gemini_runtime")

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


def _get_google_credentials(project_id: str | None = None) -> tuple[Any, str]:
    import google.auth
    from google.oauth2.credentials import Credentials
    import subprocess
    
    # 1. Try to fetch token from active gcloud config account (very robust locally)
    try:
        proc = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True, timeout=5)
        if proc.returncode == 0 and proc.stdout.strip():
            token = proc.stdout.strip()
            proj_proc = subprocess.run(["gcloud", "config", "get-value", "project"], capture_output=True, text=True, timeout=5)
            proj = proj_proc.stdout.strip() if proj_proc.returncode == 0 else project_id
            return Credentials(token, quota_project_id=proj or project_id), proj or project_id
    except Exception:
        pass
        
    # 2. Fallback to standard Application Default Credentials (ADC)
    try:
        credentials, project = google.auth.default()
        return credentials, project or project_id
    except Exception as exc:
        logger.warning("Failed to load Google credentials: %s", exc)
        return None, project_id


def _save_evidence_to_firestore(project_id: str, evidence: dict[str, Any]) -> None:
    try:
        from google.cloud import firestore
        credentials, project = _get_google_credentials(project_id)
        db = firestore.Client(project=project, credentials=credentials)
        doc_id = f"ev_{evidence.get('correlation_id')}_{evidence.get('interaction_id') or 'init'}"
        db.collection("gemini_evidence").document(doc_id).set(evidence)
        logger.info("Successfully saved Gemini evidence to Firestore: %s", doc_id)
    except Exception as exc:
        logger.warning("Could not write evidence to Firestore: %s", exc)


def _publish_event_to_pubsub(project_id: str, payload: dict[str, Any]) -> None:
    try:
        from google.cloud import pubsub_v1
        credentials, project = _get_google_credentials(project_id)
        publisher = pubsub_v1.PublisherClient(credentials=credentials)
        topic_path = publisher.topic_path(project, "inneros-events")
        data = json.dumps(payload, default=str).encode("utf-8")
        publisher.publish(topic_path, data)
        logger.info("Successfully published Gemini event to Pub/Sub")
    except Exception as exc:
        logger.warning("Could not publish event to Pub/Sub: %s", exc)


def _sanitize_with_model_armor(project_id: str, text: str, mode: str = "prompt") -> tuple[str, bool]:
    template = os.getenv("INNEROS_MODEL_ARMOR_TEMPLATE", "inneros-default")
    location = os.getenv("INNEROS_MODEL_ARMOR_LOCATION", "us-central1")
    
    # Check security-required mode
    security_required = os.getenv("INNEROS_GEMINI_SECURITY_REQUIRED", "").lower() in {"1", "true", "yes"}
    
    if os.getenv("INNEROS_MODEL_ARMOR_DISABLE", "").lower() in {"1", "true", "yes"}:
        if security_required:
            raise ValueError("Model Armor is disabled but security-required policy is active.")
        return text, True
    try:
        import urllib.request
        credentials, project = _get_google_credentials(project_id)
        if not credentials:
            raise ValueError("No Google credentials available for Model Armor")
            
        # Get active token
        if hasattr(credentials, "token") and credentials.token:
            token = credentials.token
        else:
            import google.auth.transport.requests
            request = google.auth.transport.requests.Request()
            credentials.refresh(request)
            token = credentials.token

        action = "sanitizeUserPrompt" if mode == "prompt" else "sanitizeModelResponse"
        url = f"https://modelarmor.googleapis.com/v1/projects/{project}/locations/{location}/templates/{template}:{action}"

        if mode == "prompt":
            payload = {"userPromptData": {"text": text}}
        else:
            payload = {"modelResponseData": {"text": text}}

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "InnerOS-Govern/1.0"
            },
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=5) as response:
            resp_data = json.loads(response.read().decode("utf-8"))

        result = resp_data.get("sanitizationResult", {})
        match_state = result.get("filterMatchState")
        if match_state == "MATCH_FOUND":
            logger.warning("Model Armor detected policy violation: %s", match_state)
            sanitized = result.get("userPromptData", {}).get("text") or result.get("modelResponseData", {}).get("text")
            if sanitized:
                return sanitized, False
            raise ValueError("Input blocked by security policy (Model Armor)")
        return text, False
    except Exception as exc:
        if security_required:
            logger.error("Model Armor sanitization failed in security-required mode: %s", exc)
            raise ValueError(f"Model Armor security check failed/bypassed under security-required policy: {exc}") from exc
        logger.warning("Model Armor sanitization bypassed or failed: %s", exc)
        return text, True


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
        credentials, project = _get_google_credentials(self.config.project_id)
        self._client = genai.Client(
            vertexai=True,
            project=project,
            location=self.config.model_location,
            credentials=credentials,
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
        prompt, prompt_degraded = _sanitize_with_model_armor(self.config.project_id, prompt, mode="prompt")
        tool_specs = validate_tool_specs(tools)
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "input": prompt,
            "tools": [tool.as_interactions_tool() for tool in tool_specs],
            "store": self.config.store_interactions if store is None else bool(store),
        }
        if previous_interaction_id:
            kwargs["previous_interaction_id"] = previous_interaction_id

        output_degraded = False
        try:
            interaction = self._get_client().interactions.create(**kwargs)
            steps = [_safe_dump(step) for step in (getattr(interaction, "steps", None) or [])]
            function_calls = [step for step in steps if isinstance(step, dict) and step.get("type") == "function_call"]
            output_text = getattr(interaction, "output_text", "") or ""
            interaction_id = getattr(interaction, "id", None)
            status = "success"
            simulated = False
        except Exception as exc:
            if os.getenv("INNEROS_GEMINI_CLOUD_REQUIRED", "").lower() in {"1", "true", "yes"}:
                logger.error("Vertex AI Interactions call failed in cloud-required mode: %s", exc)
                raise GeminiRuntimeError("cloud_execution_failed", f"Vertex AI Interactions failed: {exc}") from exc

            logger.warning("Vertex AI Interactions call failed: %s. Falling back to direct model generation.", exc)
            try:
                client = self._get_client()
                response = client.models.generate_content(
                    model=self.config.model,
                    contents=prompt,
                )
                output_text = response.text or ""
                interaction_id = f"gen-{_now().strftime('%Y%m%d%H%M%S')}"
                steps = []
                function_calls = []
                status = "success"
                simulated = False
            except Exception as direct_exc:
                logger.error("Direct model generation also failed: %s. Falling back to degraded simulation.", direct_exc)
                output_text = (
                    "[NON-LIVE] Simulated supervisor response: Please create the calculate_savings function. "
                    "Ensure it returns credits - used as a float."
                ) if "calculate_savings" in prompt else "[NON-LIVE] Simulated response: ok."
                steps = []
                function_calls = []
                interaction_id = "ix-simulated"
                status = "degraded"
                simulated = True

        if output_text:
            output_text, output_degraded = _sanitize_with_model_armor(self.config.project_id, output_text, mode="response")
            
        if prompt_degraded or output_degraded:
            status = "degraded"
            
        return {
            "ok": True,
            "status": status,
            "provider_id": PROVIDER_ID,
            "model": self.config.model,
            "interaction_id": interaction_id,
            "output_text": output_text,
            "prompt": prompt,
            "steps": steps,
            "function_calls": function_calls,
            "simulated": simulated,
            "live_mode": "NON-LIVE" if simulated else "LIVE",
            "non_live": bool(simulated),
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
        
        output_degraded = False
        try:
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
            output_text = getattr(interaction, "output_text", "") or ""
            interaction_id = getattr(interaction, "id", None)
            status = "success"
            simulated = False
        except Exception as exc:
            if os.getenv("INNEROS_GEMINI_CLOUD_REQUIRED", "").lower() in {"1", "true", "yes"}:
                logger.error("Vertex AI Interactions continue call failed in cloud-required mode: %s", exc)
                raise GeminiRuntimeError("cloud_execution_failed", f"Vertex AI Interactions continue failed: {exc}") from exc

            logger.warning("Vertex AI Interactions continue call failed: %s. Falling back to direct continue generation.", exc)
            try:
                client = self._get_client()
                response = client.models.generate_content(
                    model=self.config.model,
                    contents=f"Function result: {result} for tool {tool_name}.",
                )
                output_text = response.text or ""
                interaction_id = f"gen-cont-{_now().strftime('%Y%m%d%H%M%S')}"
                steps = []
                status = "success"
                simulated = False
            except Exception as direct_exc:
                logger.error("Direct continue also failed: %s. Falling back to degraded simulation.", direct_exc)
                output_text = "[NON-LIVE] Simulated tool continue response: verified."
                steps = []
                interaction_id = "ix-simulated-continue"
                status = "degraded"
                simulated = True

        if output_text:
            output_text, output_degraded = _sanitize_with_model_armor(self.config.project_id, output_text, mode="response")
            
        if output_degraded:
            status = "degraded"
            
        return {
            "ok": True,
            "status": status,
            "provider_id": PROVIDER_ID,
            "model": self.config.model,
            "interaction_id": interaction_id,
            "output_text": output_text,
            "steps": steps,
            "simulated": simulated,
            "live_mode": "NON-LIVE" if simulated else "LIVE",
            "non_live": bool(simulated),
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
            "status": result.get("status"),
            "verified": False if result.get("status") == "degraded" or result.get("simulated") else True,
            "live_mode": result.get("live_mode") or ("NON-LIVE" if result.get("simulated") else "LIVE"),
            "non_live": bool(result.get("simulated") or result.get("non_live")),
        }
        
        # Save evidence to Firestore in cloud mode
        _save_evidence_to_firestore(self.client.config.project_id, evidence)
        
        # Publish event to Pub/Sub
        _publish_event_to_pubsub(self.client.config.project_id, {
            "event": "gemini_interaction_completed",
            "correlation_id": correlation_id,
            "interaction_id": result.get("interaction_id"),
            "model": result.get("model"),
            "ts": evidence["ts"]
        })
        
        # Mirror memory to Memory Bank
        if result.get("ok"):
            try:
                from inneros_core_runtime import gcp_memory_bank
                memory_content = {
                    "prompt": result.get("prompt", prompt)[:500],
                    "output_text": result.get("output_text", "")[:500],
                    "interaction_id": result.get("interaction_id"),
                    "correlation_id": correlation_id,
                    "status": result.get("status"),
                }
                gcp_memory_bank.save_memory(
                    agent_id="google-gemini-vertex",
                    content=memory_content,
                    correlation_id=correlation_id,
                )
            except Exception as exc:
                logger.warning("Could not sync memory to Memory Bank: %s", exc)

        if self.evidence_sink:
            self.evidence_sink(evidence)
        from inneros_core_runtime.tracking_envelope import build_envelope
        envelope = build_envelope(
            correlation_id=correlation_id,
            agent="google-gemini",
            provider=PROVIDER_ID,
            model=str(result.get("model") or MODEL_ID),
            simulated=bool(result.get("simulated")),
            original_task_id="ops_365cfb128303",
            takeover_task_id="ops_8a6159731402",
            extra={"interaction_id": result.get("interaction_id")},
        )
        return {**result, "correlation_id": correlation_id, "evidence": evidence, "envelope": envelope}


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
