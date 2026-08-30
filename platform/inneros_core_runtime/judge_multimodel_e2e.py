"""Judge multi-model routing and evidence runner.

This module turns the hackathon Google multi-model requirement into a bounded,
evidence-first backend contract. Every route is reported as LIVE, PARTIAL, or
NOT_READY from probes; no route is marked PASS from static configuration alone.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from inneros_core_runtime import a2a_bridge, google_extra_models

DEFAULT_PROJECT_ID = "innerops-agentic-platform"
DEFAULT_CORRELATION = "hackathon-google-multimodel-e2e-20260830"
EVIDENCE_DIR = Path(os.getenv("INNEROS_EVIDENCE_DIR", "/home/rlopez/inneros/inneros_core/var/evidence/judge_multimodel"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project(project_id: str = "") -> str:
    return (project_id or os.getenv("GOOGLE_CLOUD_PROJECT") or DEFAULT_PROJECT_ID).strip()


def _gcloud_bin() -> str:
    for candidate in (
        os.getenv("GCLOUD_BIN", ""),
        "/home/rlopez/.local/bin/gcloud",
        "/snap/bin/gcloud",
        "gcloud",
    ):
        if candidate == "gcloud" or (candidate and Path(candidate).exists()):
            return candidate
    return "gcloud"


def _http_json(url: str, timeout: float = 5.0) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(200000).decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"raw": raw[:500]}
            return {"ok": True, "status_code": getattr(resp, "status", 200), "latency_ms": round((time.perf_counter() - started) * 1000), "data": data}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "message": str(exc)[:400], "latency_ms": round((time.perf_counter() - started) * 1000)}


def _http_post_json(url: str, body: dict[str, Any], timeout: float = 20.0) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        payload = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(200000).decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"raw": raw[:500]}
            return {"ok": True, "status_code": getattr(resp, "status", 200), "latency_ms": round((time.perf_counter() - started) * 1000), "data": data}
    except urllib.error.HTTPError as exc:
        raw = exc.read(2000).decode("utf-8", errors="replace")
        return {"ok": False, "status_code": exc.code, "error": "HTTPError", "message": raw[:400], "latency_ms": round((time.perf_counter() - started) * 1000)}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "message": str(exc)[:400], "latency_ms": round((time.perf_counter() - started) * 1000)}


def _function_gemma_local_probe(*, model: str, endpoint: str = "") -> dict[str, Any]:
    """Probe bounded function-intent routing on the local AMD vLLM lane."""

    url = (endpoint or os.getenv("INNEROS_AMD_VLLM_URL", "http://127.0.0.1:8000")).rstrip("/")
    selected_model = (model or os.getenv("INNEROS_FUNCTION_GEMMA_LOCAL_MODEL", "")).strip()
    if not selected_model:
        return {"ok": False, "error": "local_vllm_model_required", "endpoint": url}
    result = _http_post_json(
        f"{url}/v1/chat/completions",
        {
            "model": selected_model,
            "messages": [
                {"role": "system", "content": "You are a bounded function-intent classifier. Return compact JSON only."},
                {"role": "user", "content": "Classify this request for a tool router. Return only JSON with keys intent and route. Request: create a short PDF evidence summary for the judge. Allowed route values: call_tool, answer."},
            ],
            "stream": False,
            "temperature": 0,
            "max_tokens": 96,
        },
        timeout=float(os.getenv("INNEROS_FUNCTION_GEMMA_TIMEOUT", "45")),
    )
    if not result.get("ok"):
        return {"ok": False, "provider": "local-amd", "runtime": "local_vllm", "endpoint": url, "model": selected_model, "raw": result}
    choices = ((result.get("data") or {}).get("choices") or [])
    text = (((choices[0] or {}).get("message") or {}).get("content") if choices else "") or ""
    return {
        "ok": bool(text.strip()),
        "provider": "local-amd",
        "runtime": "local_vllm",
        "endpoint": url,
        "model": selected_model,
        "text_preview": text.strip()[:240],
        "latency_ms": result.get("latency_ms"),
        "cost_policy": "local_first_zero_cloud_spend",
    }


def _gcloud(args: list[str], *, project_id: str = "", timeout: int = 45) -> dict[str, Any]:
    project = _project(project_id)
    cmd = [_gcloud_bin(), *args, "--project", project, "--format", "json"]
    started = time.perf_counter()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "message": str(exc)[:400], "latency_ms": round((time.perf_counter() - started) * 1000)}
    data: Any = None
    if proc.stdout.strip():
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            data = proc.stdout[:1200]
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "data": data,
        "stderr_preview": (proc.stderr or "")[-800:],
        "latency_ms": round((time.perf_counter() - started) * 1000),
    }


def _route(status: str, *, provider: str, model: str = "", runtime: str = "", detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"status": status, "provider": provider, "model": model, "runtime": runtime, "detail": detail or {}}


def route_status(*, project_id: str = "", live_probe: bool = False, allow_live_google: bool = False) -> dict[str, Any]:
    """Return Judge selector readiness for each route."""

    project = _project(project_id)
    routes: dict[str, Any] = {}

    amd = _http_json(os.getenv("INNEROS_AMD_VLLM_MODELS_URL", "http://127.0.0.1:8000/v1/models"))
    amd_models = []
    if amd.get("ok"):
        amd_models = [str(item.get("id")) for item in ((amd.get("data") or {}).get("data") or []) if isinstance(item, dict)]
        routes["local_amd_vllm"] = _route("LIVE", provider="local-amd", model=amd_models[0] if amd_models else "unknown", runtime="vllm", detail={"models": amd_models, "latency_ms": amd.get("latency_ms")})
    else:
        routes["local_amd_vllm"] = _route("NOT_READY", provider="local-amd", runtime="vllm", detail=amd)

    intel = _http_json(os.getenv("INNEROS_INTEL_OLLAMA_TAGS_URL", "http://192.168.1.4:11434/api/tags"))
    intel_models = []
    if intel.get("ok"):
        intel_models = [str(item.get("name") or item.get("model")) for item in ((intel.get("data") or {}).get("models") or []) if isinstance(item, dict)]
        routes["local_intel_ollama"] = _route("LIVE", provider="local-intel", model=intel_models[0] if intel_models else "unknown", runtime="ollama", detail={"models": intel_models[:12], "latency_ms": intel.get("latency_ms")})
    else:
        routes["local_intel_ollama"] = _route("NOT_READY", provider="local-intel", runtime="ollama", detail=intel)

    if live_probe and allow_live_google:
        gemini = google_extra_models.smoke_lane("google-gemini-primary", project_id=project, location="global", prompt="Reply exactly: ok", allow_live=True)
        routes["gemini_35_plus"] = _route("LIVE" if gemini.get("ok") and gemini.get("live_mode") == "LIVE" else "NOT_READY", provider="google", model=str(gemini.get("model") or "gemini-3.5-flash"), runtime="vertex-genai", detail=gemini)
        gemini35 = google_extra_models.smoke_lane("google-gemini-35-bounded-review", project_id=project, prompt="Reply exactly: ok", allow_live=True)
        routes["gemini_35_bounded_review"] = _route("LIVE" if gemini35.get("ok") and gemini35.get("live_mode") == "LIVE" else "NOT_READY", provider="google", model=str(gemini35.get("model") or "gemini-3.5-flash-lite"), runtime="vertex-genai", detail=gemini35)
        google_gemma = google_extra_models.smoke_lane("google-gemma-bounded-review", project_id=project, prompt="Classify intent: call_tool or answer", allow_live=True)
        routes["google_gemma_vertex"] = _route("LIVE" if google_gemma.get("ok") and google_gemma.get("live_mode") == "LIVE" else "NOT_READY", provider="google", model=str(google_gemma.get("model") or "gemma/functiongemma"), runtime="vertex-or-model-garden", detail=google_gemma)
    else:
        routes["gemini_35_plus"] = _route("PARTIAL", provider="google", model="gemini-3.5-flash", runtime="vertex-genai", detail={"reason": "live_probe and allow_live_google required"})
        routes["gemini_35_bounded_review"] = _route("PARTIAL", provider="google", model="gemini-3.5-flash-lite", runtime="vertex-genai", detail={"reason": "live_probe and allow_live_google required"})
        routes["google_gemma_vertex"] = _route("PARTIAL", provider="google", model="gemma/functiongemma", runtime="vertex-or-model-garden", detail={"reason": "Google Gemma Vertex probe requires live_probe and allow_live_google; local function route remains available"})

    local_function = (
        _function_gemma_local_probe(model=amd_models[0] if amd_models else "")
        if live_probe and routes.get("local_amd_vllm", {}).get("status") == "LIVE"
        else {"ok": routes.get("local_amd_vllm", {}).get("status") == "LIVE", "reason": "live_probe=false; readiness inferred from local AMD vLLM models endpoint", "model": amd_models[0] if amd_models else ""}
    )
    routes["function_gemma"] = _route(
        "LIVE" if local_function.get("ok") else "NOT_READY",
        provider="local-amd",
        model=str(local_function.get("model") or (amd_models[0] if amd_models else "functiongemma-local")),
        runtime="local_vllm_function_intent",
        detail={**local_function, "replaces_blocking_vertex_dependency": True, "google_vertex_route": routes.get("google_gemma_vertex")},
    )

    routes["mi325x_cloud_burst"] = _route("PARTIAL", provider="digitalocean", model="mi325x", runtime="cloud-burst", detail={"approval_required": True, "dry_run_only_default": True})

    auto_order = ["function_gemma", "local_amd_vllm", "gemini_35_plus", "gemini_35_bounded_review", "local_intel_ollama", "mi325x_cloud_burst"]
    selected = next((name for name in auto_order if routes.get(name, {}).get("status") == "LIVE"), "none")
    routes["auto"] = _route("LIVE" if selected != "none" else "NOT_READY", provider=routes.get(selected, {}).get("provider", "none"), model=routes.get(selected, {}).get("model", ""), runtime=routes.get(selected, {}).get("runtime", ""), detail={"selected_route": selected, "order": auto_order})

    route_states = [route.get("status") for route in routes.values() if isinstance(route, dict)]
    overall_status = "LIVE" if routes["auto"]["status"] == "LIVE" else ("PARTIAL" if any(state == "LIVE" for state in route_states) else "NOT_READY")
    return {"ok": True, "project_id": project, "live_probe": live_probe, "allow_live_google": allow_live_google, "overall_status": overall_status, "routes": routes, "ts": _now()}


def _firestore_write_verify(project: str, correlation_id: str, payload: dict[str, Any], *, allow_writes: bool) -> dict[str, Any]:
    if not allow_writes:
        return {"status": "PARTIAL", "reason": "allow_writes=false", "write_attempted": False}
    try:
        from google.cloud import firestore
        from google.oauth2.credentials import Credentials
        token_proc = subprocess.run([_gcloud_bin(), "auth", "print-access-token"], capture_output=True, text=True, timeout=20, check=False)
        if token_proc.returncode != 0 or not token_proc.stdout.strip():
            return {"status": "NOT_READY", "error": "gcloud_token_unavailable", "stderr": (token_proc.stderr or "")[-500:]}
        db = firestore.Client(project=project, credentials=Credentials(token_proc.stdout.strip(), quota_project_id=project))
        doc_id = f"{correlation_id}-{int(time.time())}"
        ref = db.collection("judge_multimodel_evidence").document(doc_id)
        ref.set({**payload, "doc_id": doc_id, "written_at": _now()})
        readback = ref.get()
        return {"status": "LIVE" if readback.exists else "NOT_READY", "collection": "judge_multimodel_evidence", "doc_id": doc_id, "verified": bool(readback.exists)}
    except Exception as exc:
        return {"status": "NOT_READY", "error": type(exc).__name__, "message": str(exc)[:600]}


def _pubsub_publish(project: str, correlation_id: str, payload: dict[str, Any], *, allow_writes: bool) -> dict[str, Any]:
    if not allow_writes:
        return {"status": "PARTIAL", "reason": "allow_writes=false", "publish_attempted": False}
    try:
        from google.cloud import pubsub_v1
        from google.oauth2.credentials import Credentials
        token_proc = subprocess.run([_gcloud_bin(), "auth", "print-access-token"], capture_output=True, text=True, timeout=20, check=False)
        if token_proc.returncode != 0 or not token_proc.stdout.strip():
            return {"status": "NOT_READY", "error": "gcloud_token_unavailable", "stderr": (token_proc.stderr or "")[-500:]}
        publisher = pubsub_v1.PublisherClient(credentials=Credentials(token_proc.stdout.strip(), quota_project_id=project))
        topic_path = publisher.topic_path(project, "inneros-events")
        future = publisher.publish(topic_path, json.dumps({**payload, "correlation_id": correlation_id}, default=str).encode("utf-8"))
        message_id = future.result(timeout=20)
        return {"status": "LIVE", "topic": "inneros-events", "message_id": message_id}
    except Exception as exc:
        return {"status": "NOT_READY", "error": type(exc).__name__, "message": str(exc)[:600]}


def run_e2e(*, correlation_id: str = DEFAULT_CORRELATION, project_id: str = "", allow_live_google: bool = False, allow_writes: bool = False, dispatch_a2a: bool = True) -> dict[str, Any]:
    project = _project(project_id)
    started = time.perf_counter()
    routes = route_status(project_id=project, live_probe=True, allow_live_google=allow_live_google)
    evidence: dict[str, Any] = {
        "ok": True,
        "correlation_id": correlation_id,
        "project_id": project,
        "ts": _now(),
        "routes": routes.get("routes"),
        "steps": {},
        "cost_guard": {"google_live_requires_allow_live_google": True, "writes_require_allow_writes": True, "mi325x_created": False},
    }
    if dispatch_a2a:
        dispatch = a2a_bridge.dispatch(
            agent_id="integration-guardian",
            title="Judge multimodel E2E evidence",
            body="Verify Google multi-model Judge backend routing without production deploy.",
            correlation_id=correlation_id,
            context_id=f"ctx-{correlation_id}",
            dry_run=False,
        )
        evidence["steps"]["a2a_dispatch"] = {"status": "LIVE" if dispatch.get("ok") else "NOT_READY", **dispatch}
    else:
        evidence["steps"]["a2a_dispatch"] = {"status": "PARTIAL", "reason": "dispatch_a2a=false"}

    evidence["steps"]["firestore"] = _firestore_write_verify(project, correlation_id, evidence, allow_writes=allow_writes)
    evidence["steps"]["pubsub"] = _pubsub_publish(project, correlation_id, {"event": "judge_multimodel_e2e", "route_status": routes.get("routes", {}).get("auto")}, allow_writes=allow_writes)
    statuses = [step.get("status") for step in evidence["steps"].values()]
    route_statuses = [route.get("status") for route in (routes.get("routes") or {}).values() if isinstance(route, dict)]
    evidence["overall_status"] = "LIVE" if statuses and all(s == "LIVE" for s in statuses) and any(s == "LIVE" for s in route_statuses) else ("PARTIAL" if any(s == "LIVE" for s in statuses + route_statuses) else "NOT_READY")
    evidence["latency_ms"] = round((time.perf_counter() - started) * 1000)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE_DIR / f"{correlation_id}-{int(time.time())}.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    evidence["evidence_path"] = str(path)
    return evidence
