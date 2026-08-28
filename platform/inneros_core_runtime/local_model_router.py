"""Local model inventory and routing for RalfIA.

Local-first policy:
- prefer Ollama for summaries, classification, extraction, routing and drafts
- use external runtimes only when local quality is not enough or the task is explicitly external
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from raphiia_openai import capacity_governor_vnext, mongo_store, ralfia_time
from raphiia_openai.settings import COL_AI_ROUTING_LOG, MCP_PUBLIC_URL

GPU_ROLE = os.getenv("INNEROS_GPU_ROLE", "").strip().lower()


def _env_url(name: str, default: str) -> str:
    value = os.getenv(name, default).strip() or default
    return value.rstrip("/")


def _local_node_ips() -> set[str]:
    ips: set[str] = set()
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except Exception:
        pass
    try:
        probe = subprocess.run(["hostname", "-I"], text=True, capture_output=True, timeout=2, check=False)
        ips.update((probe.stdout or "").split())
    except Exception:
        pass
    return ips


_LOCAL_IPS = _local_node_ips()
_HOSTNAME = socket.gethostname().lower()
IS_AMD_NODE = "192.168.1.5" in _LOCAL_IPS or "amd" in _HOSTNAME
IS_INTEL_NODE = "192.168.1.4" in _LOCAL_IPS or "intel" in _HOSTNAME or "ver-10" in _HOSTNAME


if IS_AMD_NODE:
    OLLAMA_URL = "http://192.168.1.4:11434"
    VLLM_URL = "http://127.0.0.1:8000"
elif IS_INTEL_NODE:
    OLLAMA_URL = "http://127.0.0.1:11434"
    VLLM_URL = _env_url("AMD_VLLM_TUNNEL_URL", "http://127.0.0.1:18000")
elif GPU_ROLE == "vllm-primary":
    OLLAMA_URL = "http://192.168.1.4:11434"
    VLLM_URL = "http://127.0.0.1:8000"
elif GPU_ROLE == "ollama-primary":
    OLLAMA_URL = "http://127.0.0.1:11434"
    VLLM_URL = _env_url("AMD_VLLM_TUNNEL_URL", "http://127.0.0.1:18000")
else:
    OLLAMA_URL = _env_url("OLLAMA_URL", "http://192.168.1.4:11434")
    VLLM_URL = _env_url("VLLM_URL", "http://192.168.1.5:8000")
OPEN_WEBUI_URL = "http://127.0.0.1:3000"
ANYTHINGLLM_URL = "http://127.0.0.1:3001"
N8N_URL = "http://127.0.0.1:5678"
ROUTER_KEY = "local_model_router_defaults"

LOCAL_MODEL_FALLBACKS = [
    "qwen2.5:7b",
    "llama3.1:8b",
    "qwen2.5-coder:7b",
    "mistral:7b-instruct-v0.3-q4_K_M",
    "phi3.5:3.8b",
]

TASK_ALIASES = {
    "summary": "summary",
    "summarize": "summary",
    "resumen": "summary",
    "brief": "daily_brief",
    "daily_brief": "daily_brief",
    "daily brief": "daily_brief",
    "classification": "classification",
    "classify": "classification",
    "clasificar": "classification",
    "extraction": "extraction",
    "extract": "extraction",
    "extracto": "extraction",
    "reformat": "reformat",
    "format": "reformat",
    "cleanup": "reformat",
    "limpieza": "reformat",
    "draft": "draft",
    "borrador": "draft",
    "technical_report": "technical_report",
    "report": "technical_report",
    "reporte": "technical_report",
    "quote": "quote",
    "cotizacion": "quote",
    "cotización": "quote",
    "quote_intro": "quote_intro",
    "intro_cotizacion": "quote_intro",
    "routing": "routing",
    "route": "routing",
    "agent_routing": "routing",
    "notes": "notes",
    "nota": "notes",
    "operational": "operational",
    "basic_ops": "operational",
    "general_chat": "operational",
    "ops": "operational",
    "field_visit": "operational",
    "visit": "operational",
    "ocr": "vision_ocr",
    "vision": "vision_ocr",
    "image": "vision_ocr",
    "screenshot": "vision_ocr",
    "advanced_image": "vision_ocr",
    "research": "external_research",
    "investigation": "external_research",
    "architecture": "architecture_complex",
    "security_review": "critical_review",
    "critical_review": "critical_review",
    "code": "coding",
    "coding": "coding",
    "developer": "coding",
    "development": "coding",
    "programar": "coding",
    "programa": "coding",
    "programacion": "coding",
    "programación": "coding",
    "implementar": "coding",
    "implementa": "coding",
    "corrige": "coding",
    "corregir": "coding",
    "arregla": "coding",
    "arreglar": "coding",
    "crea": "coding",
    "crear": "coding",
    "bugfix": "coding",
    "bug_fix": "coding",
    "fix": "coding",
    "self_repair": "coding",
    "autoreparar": "coding",
    "autoreparacion": "coding",
    "autoreparación": "coding",
    "heavy_reasoning": "heavy_reasoning",
    "deep_coding": "heavy_reasoning",
    "architecture_coding": "heavy_reasoning",
}

TASK_MODEL_MAP = {
    "summary": "qwen2.5:7b",
    "classification": "qwen2.5:7b",
    "extraction": "qwen2.5:7b",
    "reformat": "llama3.1:8b",
    "draft": "qwen2.5:7b",
    "technical_report": "qwen2.5:14b-instruct-q4_K_M",
    "quote": "qwen2.5:7b",
    "quote_intro": "qwen2.5:7b",
    "routing": "phi3.5:3.8b",
    "daily_brief": "qwen2.5:7b",
    "notes": "qwen2.5:7b",
    "operational": "qwen2.5vl:7b",
    "coding": "qwen2.5-coder:7b",
    "heavy_reasoning": "qwen2.5:14b-instruct-q4_K_M",
    "vision_ocr": "llava:7b",
    "external_research": "qwen2.5:14b-instruct-q4_K_M",
    "architecture_complex": "qwen2.5:14b-instruct-q4_K_M",
    "critical_review": "qwen2.5:14b-instruct-q4_K_M",
}

LOCAL_OK_TASKS = {
    "summary",
    "classification",
    "extraction",
    "reformat",
    "draft",
    "technical_report",
    "quote",
    "quote_intro",
    "routing",
    "daily_brief",
    "notes",
    "operational",
    "coding",
    "heavy_reasoning",
}

EXTERNAL_TASKS = {
    "architecture_complex",
    "critical_review",
    "external_research",
    "vision_ocr",
}

HIGH_RISK_PATTERNS = re.compile(
    r"(password|secret|token|api[_ -]?key|refresh[_ -]?token|private[_ -]?key|credenciales?|secreto|contrase[a-z]+|client secret)",
    re.I,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _http_json(url: str, *, method: str = "GET", body: dict[str, Any] | None = None, timeout: float = 5.0) -> dict[str, Any]:
    try:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = {"raw": raw}
            return {"ok": True, "status": getattr(resp, "status", 200), "data": parsed}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _http_ok(url: str, timeout: float = 4.0) -> dict[str, Any]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return {"ok": True, "status": getattr(resp, "status", 200), "preview": body[:400]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _service_running(container: str) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["docker", "inspect", container, "--format", "{{.State.Status}}"],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )
        status = (proc.stdout or proc.stderr or "").strip() or "unknown"
        return {"ok": status == "running", "status": status}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _docker_env(container: str) -> list[str]:
    try:
        proc = subprocess.run(
            ["docker", "inspect", container, "--format", "{{range .Config.Env}}{{println .}}{{end}}"],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )
        return [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    except Exception:
        return []


def _gpu_snapshot() -> dict[str, Any]:
    devices: list[dict[str, Any]] = []

    # NVIDIA (primary .4)
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,utilization.gpu",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [part.strip() for part in line.split(",")]
            if len(parts) >= 4:
                devices.append(
                    {
                        "vendor": "nvidia",
                        "name": parts[0],
                        "memory_total": parts[1],
                        "memory_used": parts[2],
                        "utilization": parts[3],
                    }
                )
    except Exception:
        pass

    # AMD ROCm (ralfiia-amd .5)
    try:
        proc = subprocess.run(
            ["rocm-smi", "--showmeminfo", "vram", "--showuse"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if proc.returncode == 0 and (proc.stdout or "").strip():
            devices.append(
                {
                    "vendor": "amd",
                    "name": "ROCm GPU",
                    "report": (proc.stdout or "").strip()[:500],
                }
            )
    except Exception:
        pass

    if devices:
        return {"ok": True, "devices": devices, "available": True}

    return {"ok": False, "available": False, "devices": [], "error": "no_gpu_tools"}


def _memory_snapshot() -> dict[str, Any]:
    try:
        proc = subprocess.run(["free", "-h"], capture_output=True, text=True, timeout=4, check=False)
        return {"ok": proc.returncode == 0, "report": (proc.stdout or "").strip()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _ollama_tags() -> dict[str, Any]:
    return _http_json(f"{OLLAMA_URL}/api/tags")


def _ollama_ps() -> dict[str, Any]:
    return _http_json(f"{OLLAMA_URL}/api/ps")


def _ollama_url_for_provider(provider_id: str | None) -> str:
    if provider_id == "local-intel-4":
        return "http://192.168.1.4:11434"
    return OLLAMA_URL


def _vllm_url_for_provider(provider_id: str | None) -> str:
    if provider_id == "local-amd-5":
        return VLLM_URL
    return VLLM_URL


def _router_default(task_type: str) -> dict[str, Any] | None:
    state_doc = mongo_store.get_coordination_state(ROUTER_KEY)
    state = (state_doc.get("state") or {}) if state_doc.get("ok") else {}
    defaults = state.get("defaults") or {}
    if task_type == "heavy_reasoning":
        return defaults.get("heavy_reasoning") or defaults.get("coding")
    return defaults.get(task_type)


def _vllm_chat(
    *,
    model: str,
    prompt: str,
    system_prompt: str,
    max_tokens: int | None,
    temperature: float,
    endpoint: str | None = None,
) -> dict[str, Any]:
    vllm_url = (endpoint or VLLM_URL).rstrip("/")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "temperature": temperature,
        "max_tokens": int(max_tokens or 3200),
    }
    result = _http_json(f"{vllm_url}/v1/chat/completions", method="POST", body=payload, timeout=180)
    if not result.get("ok"):
        return {"ok": False, "error": "vllm_unavailable", "endpoint": vllm_url, "model": model, "raw": result}
    data = result.get("data", {})
    choices = data.get("choices") or []
    content = (((choices[0] or {}).get("message") or {}).get("content") if choices else "") or ""
    return {"ok": True, "backend": "vllm", "endpoint": vllm_url, "model": model, "response": content, "raw": data}


def _normalize_task(task_type: str | None, text: str) -> str:
    if task_type:
        raw = task_type.strip().lower().replace("-", "_").replace(" ", "_")
        return TASK_ALIASES.get(raw, raw)
    hay = f"{text or ''}".lower()
    for needle, mapped in TASK_ALIASES.items():
        if needle in hay:
            return mapped
    return "summary"


def _privacy_risk(text: str) -> tuple[str, bool]:
    if HIGH_RISK_PATTERNS.search(text or ""):
        return "high", True
    if re.search(r"\b(client|cliente|technical|operational|field visit|visita|site)\b", text or "", re.I):
        return "medium", False
    return "low", False


def _configured_clients() -> dict[str, Any]:
    openwebui_env = _docker_env("open-webui")
    anythingllm_env = _docker_env("anythingllm")
    n8n_env = _docker_env("n8n")

    openwebui_ollama = any("OLLAMA_BASE_URL=" in item for item in openwebui_env)
    openwebui_openai = any("OPENAI_API_BASE_URL" in item or "OPENAI_API_BASE_URLS" in item for item in openwebui_env)
    anythingllm_ollama = any("OLLAMA" in item for item in anythingllm_env)
    n8n_llm = any(any(key in item for key in ("OPENAI", "OLLAMA", "ANTHROPIC", "GEMINI")) for item in n8n_env)

    return {
        "open_webui": {
            "running": _service_running("open-webui"),
            "configured_for_ollama": openwebui_ollama,
            "configured_for_openai": openwebui_openai,
        },
        "anythingllm": {
            "running": _service_running("anythingllm"),
            "configured_for_ollama": anythingllm_ollama,
        },
        "n8n": {
            "running": _service_running("n8n"),
            "configured_for_llm": n8n_llm,
        },
    }


def _recommendations_for_model(name: str) -> list[str]:
    lower = name.lower()
    rec = []
    if "qwen2.5:7b" in lower:
        rec = ["summary", "classification", "extraction", "draft", "daily_brief", "routing"]
    elif "qwen2.5:14b" in lower:
        rec = ["technical_report", "operational", "deep_analysis", "architecture_local"]
    elif "qwen2.5-coder" in lower or "codellama" in lower or "starcoder" in lower:
        rec = ["coding", "code_review", "refactor"]
    elif "llama3.1:8b" in lower:
        rec = ["reformat", "rewrite", "summary"]
    elif "llava" in lower:
        rec = ["vision_ocr", "image_inspection"]
    elif "phi3.5" in lower:
        rec = ["routing", "fast_classification", "short_notes"]
    elif "mistral" in lower:
        rec = ["draft", "summary", "rewrite"]
    return rec


def _pick_model(task_type: str) -> str:
    routed = _router_default(task_type)
    if routed and routed.get("model_ref"):
        return str(routed["model_ref"])
    preferred = TASK_MODEL_MAP.get(task_type)
    if not preferred:
        return LOCAL_MODEL_FALLBACKS[0]
    available = {m.get("model") or m.get("name") for m in _ollama_tags().get("data", {}).get("models", [])}
    if preferred in available:
        return preferred
    for fallback in LOCAL_MODEL_FALLBACKS:
        if fallback in available:
            return fallback
    return preferred


def _log_route(
    *,
    title: str,
    body: str,
    task_type: str,
    runtime: str,
    model: str | None,
    local_ok: bool,
    external_needed: bool,
    approval_required: bool,
    reason: str,
    decision: str,
    source: str = "local_model_router",
) -> dict[str, Any]:
    db = mongo_store.get_db()
    doc = {
        "ts": _now_iso(),
        "ts_display": ralfia_time.format_log(),
        "title": title.strip(),
        "body_excerpt": (body or "")[:600],
        "task_type": task_type,
        "runtime": runtime,
        "model": model,
        "local_ok": local_ok,
        "external_needed": external_needed,
        "approval_required": approval_required,
        "reason": reason,
        "decision": decision,
        "source": source,
    }
    db[COL_AI_ROUTING_LOG].insert_one(doc)
    mongo_store.log_coordination(
        agent="CODEX",
        summary=f"AI route {runtime}: {task_type} -> {model or decision}",
        event="ai_route",
        project="ralfia-ai-routing",
        tool_used=source,
        metadata={
            "task_type": task_type,
            "runtime": runtime,
            "model": model,
            "local_ok": local_ok,
            "external_needed": external_needed,
            "approval_required": approval_required,
            "decision": decision,
        },
    )
    return mongo_store._serialize(doc)


def list_local_models() -> dict[str, Any]:
    tags = _ollama_tags()
    ps = _ollama_ps()
    models = tags.get("data", {}).get("models", []) if tags.get("ok") else []
    loaded = {m.get("model") or m.get("name") for m in ps.get("data", {}).get("models", [])} if ps.get("ok") else set()
    clients = _configured_clients()
    gpu = _gpu_snapshot()
    items = []
    for model in models:
        name = model.get("model") or model.get("name")
        details = model.get("details") or {}
        size_bytes = int(model.get("size") or 0)
        items.append(
            {
                "name": name,
                "size_bytes": size_bytes,
                "size_gb": round(size_bytes / (1024**3), 2) if size_bytes else None,
                "parameter_size": details.get("parameter_size"),
                "quantization_level": details.get("quantization_level"),
                "family": details.get("family") or (details.get("families") or [None])[0],
                "endpoint": f"{OLLAMA_URL}/api/chat",
                "loaded": name in loaded,
                "running_backend": "GPU" if gpu.get("available") else "CPU",
                "recommended_for": _recommendations_for_model(name or ""),
                "configured_clients": [
                    client
                    for client, cfg in clients.items()
                    if (client == "open_webui" and cfg.get("configured_for_ollama"))
                    or (client == "anythingllm" and cfg.get("configured_for_ollama"))
                    or (client == "n8n" and cfg.get("configured_for_llm"))
                ],
            }
        )
    return {
        "ok": True,
        "endpoint": OLLAMA_URL,
        "loaded_models": sorted(list(loaded)),
        "configured_clients": clients,
        "gpu": gpu,
        "models": items,
        "count": len(items),
    }


def local_model_health() -> dict[str, Any]:
    ollama_tags = _http_ok(f"{OLLAMA_URL}/api/tags")
    ollama_ps = _http_ok(f"{OLLAMA_URL}/api/ps")
    vllm_models = _http_ok(f"{VLLM_URL}/v1/models")
    open_webui = {
        "container": _service_running("open-webui"),
        "port_probe": {"ok": False, "skipped": "no explicit host port mapping detected for open-webui"},
    }
    anythingllm = {
        "container": _service_running("anythingllm"),
        "port_probe": _http_ok(f"{ANYTHINGLLM_URL}/api/system/status"),
    }
    n8n = {
        "container": _service_running("n8n"),
        "port_probe": _http_ok(f"{N8N_URL}/healthz"),
    }
    gpu = _gpu_snapshot()
    memory = _memory_snapshot()
    clients = _configured_clients()
    ok = bool(ollama_tags.get("ok") or vllm_models.get("ok"))
    status = {
        "ok": ok,
        "ollama": {
            "endpoint": OLLAMA_URL,
            "api_tags": ollama_tags,
            "api_ps": ollama_ps,
            "models_loaded_now": ollama_ps.get("data", {}).get("models", []) if ollama_ps.get("ok") else [],
        },
        "vllm": {
            "endpoint": VLLM_URL,
            "api_models": vllm_models,
        },
        "open_webui": open_webui,
        "anythingllm": anythingllm,
        "n8n": n8n,
        "gpu": gpu,
        "memory": memory,
        "configured_clients": clients,
        "local_first": True,
        "ts": _now_iso(),
    }
    try:
        cpu_ratio = 0.0
        if hasattr(os, "getloadavg"):
            cpu_ratio = (os.getloadavg()[0] / max(1, os.cpu_count() or 1))
        status["capacity_governor_vnext"] = capacity_governor_vnext.classify_capacity(
            cpu_load_ratio=cpu_ratio,
            ram_used_ratio=0.0,
            vram_used_ratio=0.0,
            active_worker_count=0,
            sustained_samples=1,
        )
        if IS_INTEL_NODE:
            status["capacity_governor_vnext"]["intel_baseline"] = {
                "required_models": sorted(capacity_governor_vnext.INTEL_BASELINE_MODELS),
                "loaded_models": sorted(m.get("model") for m in capacity_governor_vnext.ollama_loaded_models() if m.get("model")),
            }
    except Exception as exc:
        status["capacity_governor_vnext"] = {"ok": False, "error": str(exc)}
    return status


def classify_task_runtime(text: str, task_type: str | None = None) -> dict[str, Any]:
    normalized = _normalize_task(task_type, text)
    privacy_risk, privacy_flag = _privacy_risk(text)
    local_ok = normalized in LOCAL_OK_TASKS
    external_needed = normalized in EXTERNAL_TASKS
    approval_required = privacy_flag or external_needed
    reason = "local-first default"
    routed = _router_default(normalized)

    if normalized in {"architecture_complex", "critical_review"}:
        reason = "complex reasoning or review is better handled externally"
    elif normalized == "external_research":
        reason = "external research is explicitly external"
    elif normalized == "vision_ocr":
        reason = "vision/OCR can use local llava, but external may be needed if quality is insufficient"
    elif normalized in LOCAL_OK_TASKS:
        reason = "task is well suited for local runtime"

    model = _pick_model(normalized) if local_ok else None
    return {
        "ok": True,
        "task_type": normalized,
        "privacy_risk": privacy_risk,
        "local_ok": local_ok,
        "recommended_model": model,
        "recommended_provider": routed.get("provider_id") if routed else ("local-intel-4" if local_ok else None),
        "recommended_backend": "vllm" if routed and routed.get("provider_id") == "local-amd-5" else ("ollama" if local_ok else None),
        "external_needed": external_needed,
        "approval_required": approval_required,
        "reason": reason,
        "route_hint": "local_model" if local_ok and not external_needed else ("human_review" if privacy_flag else "external"),
    }


def route_ai_task(title: str, body: str, task_type: str | None = None) -> dict[str, Any]:
    text = f"{title}\n{body}"
    classification = classify_task_runtime(text, task_type=task_type)
    normalized = classification["task_type"]
    privacy_risk = classification["privacy_risk"]
    local_ok = classification["local_ok"]
    external_needed = classification["external_needed"]
    approval_required = classification["approval_required"]
    local_model = classification["recommended_model"]
    provider_id = classification.get("recommended_provider")
    backend = classification.get("recommended_backend")

    if normalized == "coding" and not local_ok:
        runtime = "human_review"
        decision = "hold_for_review"
        model = None
        reason = "coding task has no local-safe route"
    elif privacy_risk == "high":
        runtime = "human_review"
        decision = "hold_for_review"
        model = None
        reason = "high privacy risk"
    elif local_ok and not external_needed:
        runtime = "local_vllm" if backend == "vllm" else "local_model"
        decision = "execute_local"
        model = local_model
        reason = classification["reason"]
    elif normalized == "vision_ocr":
        runtime = "gemini"
        decision = "execute_external"
        model = None
        reason = "vision/OCR external route preferred when local llava is not enough"
    elif normalized in {"architecture_complex", "critical_review"}:
        runtime = "openai"
        decision = "execute_external"
        model = None
        reason = "critical architecture/review routed to external model"
    elif normalized == "external_research":
        runtime = "gemini"
        decision = "execute_external"
        model = None
        reason = "external research routed externally"
    else:
        runtime = "human_review" if approval_required else "local_model"
        decision = "hold_for_review" if runtime == "human_review" else "execute_local"
        model = local_model if runtime == "local_model" else None
        reason = classification["reason"]

    record = _log_route(
        title=title,
        body=body,
        task_type=normalized,
        runtime=runtime,
        model=model,
        local_ok=local_ok,
        external_needed=external_needed,
        approval_required=approval_required,
        reason=reason,
        decision=decision,
    )
    return {
        "ok": True,
        "task_type": normalized,
        "runtime": runtime,
        "decision": decision,
        "local_model": model,
        "local_ok": local_ok,
        "external_needed": external_needed,
        "approval_required": approval_required,
        "reason": reason,
        "routing_log": record,
        "provider_id": provider_id,
        "backend": backend,
        "selected_node": "amd" if provider_id == "local-amd-5" else ("intel" if provider_id == "local-intel-4" else None),
    }


def run_local_model(
    *,
    task_type: str,
    prompt: str,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.2,
) -> dict[str, Any]:
    classification = classify_task_runtime(prompt, task_type=task_type)
    selected = model or classification["recommended_model"] or _pick_model(classification["task_type"])
    provider_id = classification.get("recommended_provider")
    backend = classification.get("recommended_backend")
    ollama_url = _ollama_url_for_provider(provider_id)
    vllm_url = _vllm_url_for_provider(provider_id)
    health = local_model_health()
    provider_health = _http_ok(f"{vllm_url}/v1/models") if backend == "vllm" and provider_id == "local-amd-5" else _http_ok(f"{ollama_url}/api/tags")
    if backend == "vllm" and provider_id == "local-amd-5" and not provider_health.get("ok"):
        return {
            "ok": False,
            "error": "amd_vllm_unreachable_from_intel" if GPU_ROLE == "ollama-primary" else "amd_vllm_unreachable",
            "endpoint": vllm_url,
            "health": health,
            "provider_health": provider_health,
            "recommended_model": selected,
            "selected_model": selected,
            "selected_node": "amd",
            "provider_id": provider_id,
            "fallback_silent": False,
            "fallback_reason": "amd_vllm_unreachable_from_intel" if GPU_ROLE == "ollama-primary" else "amd_vllm_unreachable",
        }
    if not (health.get("ok") or provider_health.get("ok")):
        return {
            "ok": False,
            "error": "local_runtime_unavailable",
            "health": health,
            "provider_health": provider_health,
            "recommended_model": selected,
        }

    system_prompt = {
        "summary": "Resume de forma clara y breve.",
        "classification": "Devuelve una clasificacion concisa.",
        "extraction": "Extrae datos clave en formato compacto.",
        "reformat": "Reescribe y ordena el texto sin agregar relleno.",
        "draft": "Escribe un borrador interno util y breve.",
        "technical_report": "Genera un informe tecnico estructurado y util.",
        "quote": "Genera un borrador de cotizacion corto y util.",
        "quote_intro": "Redacta introduccion comercial breve para cotizacion; no informe tecnico completo.",
        "routing": "Decide ruta operativa con criterio pragmatico.",
        "daily_brief": "Genera un daily brief breve, claro y accionable.",
        "notes": "Redacta notas limpias y utiles.",
    "operational": "Analiza operacion tecnica con foco en datos y pendientes.",
    "coding": "Ayuda con codigo de forma precisa y directa. Si requiere editar repos, usa Local Execution Plane/dispatcher con rama, tests y evidencia; no finjas cambios no ejecutados.",
        "heavy_reasoning": "Razona con rigor sobre arquitectura y codigo. Devuelve resultados estructurados y evita inventar dependencias o rutas.",
    }.get(classification["task_type"], "Responde de forma breve y util.")

    if backend == "vllm" and provider_id == "local-amd-5":
        result = _vllm_chat(
            model=selected,
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            endpoint=vllm_url,
        )
        if not result.get("ok"):
            _log_route(
                title=classification["task_type"],
                body=prompt,
                task_type=classification["task_type"],
                runtime="local_vllm",
                model=selected,
                local_ok=True,
                external_needed=False,
                approval_required=False,
                reason="vLLM execution failed; no silent fallback",
                decision="error",
            )
            return {
                **result,
                "task_type": classification["task_type"],
                "selected_model": selected,
                "selected_node": "amd",
                "provider_id": provider_id,
                "fallback_silent": False,
            }
        log = _log_route(
            title=classification["task_type"],
            body=prompt,
            task_type=classification["task_type"],
            runtime="local_vllm",
            model=selected,
            local_ok=True,
            external_needed=False,
            approval_required=False,
            reason=classification["reason"],
            decision="executed_local_vllm",
        )
        return {
            **result,
            "runtime": "local_vllm",
            "task_type": classification["task_type"],
            "selected_model": selected,
            "selected_node": "amd",
            "provider_id": provider_id,
            "fallback_silent": False,
            "routing_log": log,
        }

    payload = {
        "model": selected,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {
            "temperature": temperature,
        },
    }
    if max_tokens:
        payload["options"]["num_predict"] = int(max_tokens)

    result = _http_json(f"{ollama_url}/api/chat", method="POST", body=payload, timeout=180)
    if not result.get("ok"):
        _log_route(
            title=classification["task_type"],
            body=prompt,
            task_type=classification["task_type"],
            runtime="local_model",
            model=selected,
            local_ok=True,
            external_needed=False,
            approval_required=False,
            reason="local model execution failed",
            decision="error",
        )
        return {
            "ok": False,
            "error": result.get("error"),
            "model": selected,
            "endpoint": f"{ollama_url}/api/chat",
            "payload": payload,
        }

    data = result.get("data", {})
    content = data.get("message", {}).get("content", "")
    log = _log_route(
        title=classification["task_type"],
        body=prompt,
        task_type=classification["task_type"],
        runtime="local_model",
        model=selected,
        local_ok=True,
        external_needed=False,
        approval_required=False,
        reason=classification["reason"],
        decision="executed_local",
    )
    return {
        "ok": True,
        "runtime": "local_model",
        "model": selected,
        "endpoint": f"{ollama_url}/api/chat",
        "task_type": classification["task_type"],
        "response": content,
        "raw": data,
        "routing_log": log,
        "selected_model": selected,
        "selected_node": "intel" if provider_id == "local-intel-4" else None,
        "provider_id": provider_id,
        "fallback_silent": False,
    }


def get_ai_usage_report(limit: int = 200) -> dict[str, Any]:
    db = mongo_store.get_db()
    limit = max(1, min(int(limit), 1000))
    cursor = db[COL_AI_ROUTING_LOG].find({}).sort("ts", -1).limit(limit)
    events = [mongo_store._serialize(doc) for doc in cursor]
    runtime_counts = Counter(event.get("runtime", "unknown") for event in events)
    model_counts = Counter(event.get("model") or "none" for event in events if event.get("runtime") == "local_model")
    task_counts = Counter(event.get("task_type", "unknown") for event in events)
    local_calls = runtime_counts.get("local_model", 0)
    external_calls = runtime_counts.get("gemini", 0) + runtime_counts.get("openai", 0)
    human_review = runtime_counts.get("human_review", 0)
    estimated_savings_units = local_calls
    return {
        "ok": True,
        "ts": _now_iso(),
        "total_events": len(events),
        "runtime_counts": dict(runtime_counts),
        "task_counts": dict(task_counts),
        "model_counts": dict(model_counts),
        "local_calls": local_calls,
        "external_calls": external_calls,
        "human_review": human_review,
        "estimated_external_calls_avoided": estimated_savings_units,
        "estimated_credit_savings_units": estimated_savings_units,
        "notes": [
            "Credits saved is an estimate based on local executions vs external routing.",
            "Use the report as a control signal, not as billing truth.",
        ],
        "recent_events": events[:20],
    }


def _fallback_daily_brief(payload: dict[str, Any]) -> str:
    local = payload.get("local_model_health", {})
    report = payload.get("usage_report", {})
    summary = payload.get("coordination_summary", {})
    publish = payload.get("publish_logs", {})
    lines = [
        "# Daily Brief",
        "",
        "## Estado",
        f"- AG-25 events: {summary.get('total_events', 0)}",
        f"- Local runtime ok: {bool(local.get('ok'))}",
        f"- Local calls: {report.get('local_calls', 0)}",
        f"- External calls: {report.get('external_calls', 0)}",
        f"- Publish logs: {len(publish.get('destinations', [])) if isinstance(publish, dict) else 0}",
        "",
        "## Modelos locales",
    ]
    models = payload.get("local_models", {}).get("models", [])
    for model in models[:5]:
        lines.append(f"- {model.get('name')} ({model.get('parameter_size')}, {model.get('quantization_level')})")
    lines += [
        "",
        "## Bloqueos",
        "- Ninguno bloqueante detectado por el brief de fallback.",
        "",
        "## Siguientes pasos",
        "- Mantener local-first en resúmenes, clasificacion y borradores.",
        "- Dejar externo solo para arquitectura compleja, revision critica o vision/OCR duro.",
    ]
    return "\n".join(lines).strip() + "\n"


def generate_daily_brief(limit: int = 20, model: str | None = None) -> dict[str, Any]:
    from raphiia_openai import mongo_store

    coordination_summary = mongo_store.get_coordination_summary(limit=limit)
    publish_logs = mongo_store.get_publish_logs(limit=min(limit, 20))
    local_models = list_local_models()
    local_health = local_model_health()
    usage_report = get_ai_usage_report(limit=limit)

    payload = {
        "coordination_summary": coordination_summary,
        "publish_logs": publish_logs,
        "local_models": local_models,
        "local_model_health": local_health,
        "usage_report": usage_report,
    }

    prompt = json.dumps(payload, ensure_ascii=False, indent=2)
    route = route_ai_task(
        title="daily_brief",
        body="Resumir estado operativo del dia usando local-first y sin ruido.",
        task_type="daily_brief",
    )
    if route.get("runtime") == "local_model":
        result = run_local_model(
            task_type="daily_brief",
            prompt=prompt,
            model=model or route.get("local_model"),
            max_tokens=450,
            temperature=0.2,
        )
        if result.get("ok"):
            brief = result.get("response", "")
            return {
                "ok": True,
                "runtime": "local_model",
                "model": result.get("model"),
                "brief_markdown": brief,
                "payload": payload,
                "routing": route,
            }

    fallback = _fallback_daily_brief(payload)
    return {
        "ok": True,
        "runtime": route.get("runtime", "fallback"),
        "model": route.get("local_model"),
        "brief_markdown": fallback,
        "payload": payload,
        "routing": route,
        "fallback": True,
    }


def cognitive_kernel_check(objective: str, context: str | None = None) -> dict[str, Any]:
    text = f"{objective}\n{context or ''}".strip()
    classification = classify_task_runtime(text)
    if classification["privacy_risk"] == "high":
        runtime = "human_review"
        suggested_action = "hold_for_review"
    elif classification["local_ok"] and not classification["external_needed"]:
        runtime = "local_model"
        suggested_action = "run_local_model"
    elif classification["task_type"] in {"vision_ocr", "external_research"}:
        runtime = "gemini"
        suggested_action = "use_external"
    elif classification["task_type"] in {"architecture_complex", "critical_review"}:
        runtime = "openai"
        suggested_action = "use_external"
    else:
        runtime = "human_review" if classification["approval_required"] else "local_model"
        suggested_action = "review" if runtime == "human_review" else "run_local_model"
    known = {
        "what_i_know": [
            "Local Ollama is available on 11434",
            f"Recommended runtime: {runtime}",
            f"Recommended local model: {classification.get('recommended_model')}",
        ],
        "what_i_want": objective,
        "recommended_agent": runtime,
        "risks": [
            f"privacy={classification.get('privacy_risk')}",
            f"external_needed={classification.get('external_needed')}",
        ],
        "permission_required": "Rafael approval" if classification.get("approval_required") else "none",
        "suggested_action": suggested_action,
    }
    return {
        "ok": True,
        "objective": objective,
        "context": context,
        "task_type": classification["task_type"],
        "local_ok": classification["local_ok"],
        "external_needed": classification["external_needed"],
        "recommended_model": classification["recommended_model"],
        "route": {
            "runtime": runtime,
            "model": classification["recommended_model"] if runtime == "local_model" else None,
            "approval_required": classification["approval_required"],
            "reason": classification["reason"],
        },
        "kernel": known,
    }
