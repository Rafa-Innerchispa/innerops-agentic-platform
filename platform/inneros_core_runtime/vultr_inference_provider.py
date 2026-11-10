"""Vultr Serverless Inference Provider for InnerOS.

Exposes OpenAI-compatible serverless inference (DeepSeek, Qwen 3.8, GLM,
MiniMax, Embeddings, Reranking, and Whisper audio transcription) powered by
Vultr Serverless Inference using promotional credits stored in owner_vault.

Local AMD 1.5 (Radeon AI PRO R9700 32GB) remains the default primary.
Vultr Serverless Inference acts as a high-speed cloud burst, embedding,
reranking, and specialized model capability.
"""

from __future__ import annotations

import io
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from raphiia_openai import mongo_store, owner_vault

PROVIDER_ID = "vultr-inference"
VAULT_CATEGORY = "cloud_provider"
VAULT_KEY = "vultr_inference_api_key"
API_BASE = "https://api.vultrinference.com/v1"
AUDIT_COLLECTION = "ralfia_vultr_inference_audit"
DEFAULT_CHAT_MODEL = "deepseek-v4.1-flash-1017"
DEFAULT_EMBED_MODEL = "qwen3-embedding-4b"
DEFAULT_RERANK_MODEL = "bge-reranker-v2-m3"
DEFAULT_WHISPER_MODEL = "whisper-large-v3-turbo"
MAX_TEST_BUDGET_USD = 5.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_api_key() -> str:
    cred = owner_vault.get_owner_credential(VAULT_KEY, category=VAULT_CATEGORY, reveal=True)
    if cred and cred.get("ok") and cred.get("secret"):
        return str(cred["secret"]).strip()
    cred2 = owner_vault.get_owner_credential(VAULT_KEY, category="model_api_provider", reveal=True)
    if cred2 and cred2.get("ok") and cred2.get("secret"):
        return str(cred2["secret"]).strip()
    return ""


def _audit(action: str, payload: dict[str, Any]) -> None:
    safe = _redact(payload)
    safe.setdefault("provider", PROVIDER_ID)
    safe.setdefault("action", action)
    safe.setdefault("timestamp", _now())
    try:
        db = mongo_store.get_db()
        db[AUDIT_COLLECTION].insert_one(safe)
    except Exception:
        pass


def _redact(data: Any) -> Any:
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if any(s in str(k).lower() for s in ("token", "secret", "key", "password", "auth")):
                out[k] = "[REDACTED]"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(data, list):
        return [_redact(i) for i in data]
    return data


def _check_budget() -> tuple[bool, float]:
    try:
        db = mongo_store.get_db()
        pipeline = [
            {"$match": {"provider": PROVIDER_ID, "action": {"$in": ["chat", "embeddings", "rerank", "audio"]}}},
            {"$group": {"_id": None, "total_est_usd": {"$sum": "$estimated_cost_usd"}}}
        ]
        res = list(db[AUDIT_COLLECTION].aggregate(pipeline))
        spent = float(res[0]["total_est_usd"]) if res and res[0].get("total_est_usd") else 0.0
        return spent < MAX_TEST_BUDGET_USD, spent
    except Exception:
        return True, 0.0


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    return round((prompt_tokens * 0.0000002) + (completion_tokens * 0.0000008), 6)


def list_models() -> dict[str, Any]:
    url = f"{API_BASE}/models"
    key = _get_api_key()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            models = data.get("data", [])
            return {
                "ok": True,
                "count": len(models),
                "models": [m.get("id") for m in models],
                "details": models,
            }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "count": 0, "models": []}


def chat_completion(
    messages: list[dict[str, str]],
    model: str = DEFAULT_CHAT_MODEL,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    stream: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    within_budget, spent = _check_budget()
    if not within_budget:
        return {
            "ok": False,
            "error": "BUDGET_CAP_EXCEEDED",
            "message": f"Vultr inference testing spend reached limit (${spent:.2f} / ${MAX_TEST_BUDGET_USD:.2f}). Explicit approval required.",
            "provider": PROVIDER_ID,
        }

    key = _get_api_key()
    if not key:
        return {"ok": False, "error": "MISSING_API_KEY", "provider": PROVIDER_ID}

    url = f"{API_BASE}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": stream,
        **kwargs,
    }
    t0 = time.time()
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            elapsed_ms = round((time.time() - t0) * 1000, 2)
            data = json.loads(resp.read().decode())
            usage = data.get("usage", {})
            p_tok = usage.get("prompt_tokens", 0)
            c_tok = usage.get("completion_tokens", 0)
            est_cost = _estimate_cost(model, p_tok, c_tok)
            choice = data.get("choices", [{}])[0].get("message", {})

            _audit("chat", {
                "model": model,
                "latency_ms": elapsed_ms,
                "usage": usage,
                "estimated_cost_usd": est_cost,
                "status_code": resp.status,
            })

            return {
                "ok": True,
                "provider": PROVIDER_ID,
                "model": model,
                "latency_ms": elapsed_ms,
                "content": choice.get("content", ""),
                "reasoning_content": choice.get("reasoning_content", ""),
                "usage": usage,
                "estimated_cost_usd": est_cost,
            }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        _audit("chat_error", {"model": model, "status_code": exc.code, "error": body})
        return {"ok": False, "error": f"HTTP_{exc.code}", "details": body, "provider": PROVIDER_ID}
    except Exception as exc:
        _audit("chat_error", {"model": model, "error": str(exc)})
        return {"ok": False, "error": str(exc), "provider": PROVIDER_ID}


def embeddings(
    texts: Union[str, list[str]],
    model: str = DEFAULT_EMBED_MODEL,
) -> dict[str, Any]:
    within_budget, spent = _check_budget()
    if not within_budget:
        return {"ok": False, "error": "BUDGET_CAP_EXCEEDED", "provider": PROVIDER_ID}

    key = _get_api_key()
    if not key:
        return {"ok": False, "error": "MISSING_API_KEY", "provider": PROVIDER_ID}

    if isinstance(texts, str):
        texts = [texts]

    url = f"{API_BASE}/embeddings"
    payload = {"model": model, "input": texts}
    t0 = time.time()
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            elapsed_ms = round((time.time() - t0) * 1000, 2)
            data = json.loads(resp.read().decode())
            items = data.get("data", [])
            vectors = [item.get("embedding", []) for item in items]
            dim = len(vectors[0]) if vectors else 0
            usage = data.get("usage", {})
            p_tok = usage.get("prompt_tokens", 0)
            est_cost = _estimate_cost(model, p_tok, 0)

            _audit("embeddings", {
                "model": model,
                "input_count": len(texts),
                "dimension": dim,
                "latency_ms": elapsed_ms,
                "usage": usage,
                "estimated_cost_usd": est_cost,
            })

            return {
                "ok": True,
                "provider": PROVIDER_ID,
                "model": model,
                "count": len(vectors),
                "dimension": dim,
                "embeddings": vectors,
                "latency_ms": elapsed_ms,
                "usage": usage,
                "estimated_cost_usd": est_cost,
            }
    except Exception as exc:
        _audit("embeddings_error", {"model": model, "error": str(exc)})
        return {"ok": False, "error": str(exc), "provider": PROVIDER_ID}


def rerank(
    query: str,
    documents: list[str],
    top_n: int = 5,
    model: str = DEFAULT_RERANK_MODEL,
) -> dict[str, Any]:
    within_budget, spent = _check_budget()
    if not within_budget:
        return {"ok": False, "error": "BUDGET_CAP_EXCEEDED", "provider": PROVIDER_ID}

    key = _get_api_key()
    if not key:
        return {"ok": False, "error": "MISSING_API_KEY", "provider": PROVIDER_ID}

    url = f"{API_BASE}/rerank"
    payload = {
        "model": model,
        "query": query,
        "documents": documents,
        "top_n": min(top_n, len(documents)),
    }
    t0 = time.time()
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            elapsed_ms = round((time.time() - t0) * 1000, 2)
            data = json.loads(resp.read().decode())
            results = data.get("results", [])

            _audit("rerank", {
                "model": model,
                "query": query[:100],
                "documents_count": len(documents),
                "latency_ms": elapsed_ms,
                "estimated_cost_usd": 0.0001,
            })

            return {
                "ok": True,
                "provider": PROVIDER_ID,
                "model": model,
                "results": results,
                "latency_ms": elapsed_ms,
            }
    except Exception as exc:
        _audit("rerank_error", {"model": model, "error": str(exc)})
        return {"ok": False, "error": str(exc), "provider": PROVIDER_ID}


def transcribe_audio(
    audio_bytes: bytes,
    filename: str = "audio.wav",
    model: str = DEFAULT_WHISPER_MODEL,
) -> dict[str, Any]:
    within_budget, spent = _check_budget()
    if not within_budget:
        return {"ok": False, "error": "BUDGET_CAP_EXCEEDED", "provider": PROVIDER_ID}

    key = _get_api_key()
    if not key:
        return {"ok": False, "error": "MISSING_API_KEY", "provider": PROVIDER_ID}

    url = f"{API_BASE}/audio/transcriptions"
    boundary = "----WebKitFormBoundaryInnerOS"
    body = bytearray()
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(b'Content-Disposition: form-data; name="model"\r\n\r\n')
    body.extend(f"{model}\r\n".encode())

    body.extend(f"--{boundary}\r\n".encode())
    body.extend(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode())
    body.extend(b'Content-Type: audio/wav\r\n\r\n')
    body.extend(audio_bytes)
    body.extend(b'\r\n')
    body.extend(f"--{boundary}--\r\n".encode())

    t0 = time.time()
    try:
        req = urllib.request.Request(
            url,
            data=bytes(body),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            elapsed_ms = round((time.time() - t0) * 1000, 2)
            data = json.loads(resp.read().decode())
            text = data.get("text", "")
            usage = data.get("usage", {})

            _audit("audio", {
                "model": model,
                "latency_ms": elapsed_ms,
                "usage": usage,
                "estimated_cost_usd": 0.0005,
            })

            return {
                "ok": True,
                "provider": PROVIDER_ID,
                "model": model,
                "text": text,
                "usage": usage,
                "latency_ms": elapsed_ms,
            }
    except Exception as exc:
        _audit("audio_error", {"model": model, "error": str(exc)})
        return {"ok": False, "error": str(exc), "provider": PROVIDER_ID}


def status() -> dict[str, Any]:
    key = _get_api_key()
    within_budget, spent = _check_budget()
    return {
        "ok": bool(key),
        "provider_id": PROVIDER_ID,
        "configured": bool(key),
        "key_present": bool(key),
        "api_base": API_BASE,
        "default_models": {
            "chat": DEFAULT_CHAT_MODEL,
            "embeddings": DEFAULT_EMBED_MODEL,
            "rerank": DEFAULT_RERANK_MODEL,
            "audio": DEFAULT_WHISPER_MODEL,
        },
        "budget": {
            "max_test_budget_usd": MAX_TEST_BUDGET_USD,
            "spent_usd": round(spent, 4),
            "within_budget": within_budget,
        },
        "funding_source": "vultr_promotional_credit",
        "initial_credit_usd": 250.0,
    }


def resource_provider_document() -> dict[str, Any]:
    st = status()
    return {
        "provider_id": PROVIDER_ID,
        "label": "Vultr Serverless Inference",
        "kind": "external_model_provider",
        "capabilities": [
            "coding",
            "heavy_reasoning",
            "embeddings",
            "rerank",
            "speech_transcription",
            "cloud_burst",
        ],
        "local_first": False,
        "status": "active" if st.get("ok") else "credential_not_configured",
        "auth_mode": "owner_vault",
        "credential_ref": "cred_cloud_provider_vultr_inference_api_key",
        "default_model": DEFAULT_CHAT_MODEL,
        "cost_policy": "explicit_burst_only",
        "funding_provider": "vultr",
        "billing": {
            "credit_account": "vultr_promotional_credit",
            "initial_credit_usd": 250.0,
            "budget_cap_usd": MAX_TEST_BUDGET_USD,
        },
        "governance": "local AMD 1.5 primary default; Vultr cloud burst on-demand; strict budget cap",
    }


def model_provider_document() -> dict[str, Any]:
    return {
        "model_provider": "vultr-inference",
        "provider_id": PROVIDER_ID,
        "model_ref": DEFAULT_CHAT_MODEL,
        "task_classes": [
            "coding",
            "heavy_reasoning",
            "embeddings",
            "rerank",
            "speech_transcription",
            "cloud_burst",
        ],
        "priority": 50,
        "cost_policy": "explicit_burst_only",
        "local_first": False,
    }
