"""Reusable Cognee memory provider for InnerOS.

The provider owns Cognee connectivity. Product repositories consume these
capabilities through MCP/Resource Fabric and never store Cognee credentials.
"""

from __future__ import annotations

import importlib
import json
import os
from typing import Any


DEFAULT_DATASET = "inneros-personal-brain"


def _settings() -> dict[str, Any]:
    return {
        "service_url": (
            os.getenv("COGNEE_SERVICE_URL")
            or os.getenv("COGNEE_BASE_URL")
            or ""
        ).rstrip("/"),
        "api_key": os.getenv("COGNEE_API_KEY", ""),
        "dataset": os.getenv("COGNEE_DATASET", DEFAULT_DATASET),
    }


def _load_cognee() -> Any:
    return importlib.import_module("cognee")


async def _configure_cloud(cognee: Any, settings: dict[str, Any]) -> None:
    if settings["service_url"] and settings["api_key"]:
        await cognee.serve(
            url=settings["service_url"],
            api_key=settings["api_key"],
        )


def _normalize_hit(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        data = dict(item)
        text = data.get("text") or data.get("content") or data.get("answer")
        return {"text": str(text if text is not None else data), "metadata": data}

    text = getattr(item, "text", None)
    metadata = getattr(item, "metadata", None)
    return {
        "text": str(text if text is not None else item),
        "metadata": metadata if isinstance(metadata, dict) else {},
        "source": getattr(item, "source", None),
        "search_type": str(getattr(item, "search_type", "") or ""),
        "dataset": getattr(item, "dataset_name", None),
    }


async def status() -> dict[str, Any]:
    settings = _settings()
    try:
        _load_cognee()
        sdk_present = True
        error = None
    except Exception as exc:
        sdk_present = False
        error = f"{type(exc).__name__}: {exc}"

    return {
        "ok": sdk_present,
        "provider": "cognee",
        "sdk_present": sdk_present,
        "service_url_configured": bool(settings["service_url"]),
        "credential_present": bool(settings["api_key"]),
        "dataset": settings["dataset"],
        "credential_source": "server-side environment / owner vault projection",
        "error": error,
    }


async def preflight(live: bool = False) -> dict[str, Any]:
    current = await status()
    if not current["sdk_present"]:
        return current

    if not current["credential_present"] or not current["service_url_configured"]:
        return {
            **current,
            "ok": False,
            "live": False,
            "error": "cognee_cloud_configuration_incomplete",
        }

    if not live:
        return {**current, "ok": True, "live": False}

    settings = _settings()
    cognee = _load_cognee()
    try:
        await _configure_cloud(cognee, settings)
        result = await cognee.recall(
            "InnerOS Cognee connectivity preflight",
            datasets=[settings["dataset"]],
            top_k=1,
            only_context=True,
        )
        return {
            **current,
            "ok": True,
            "live": True,
            "probe_count": len(list(result or [])),
        }
    except Exception as exc:
        return {
            **current,
            "ok": False,
            "live": True,
            "error": f"{type(exc).__name__}: {exc}",
        }


async def memory_search(
    query: str,
    limit: int = 8,
    dataset: str | None = None,
    only_context: bool = True,
) -> dict[str, Any]:
    if not query.strip():
        return {"ok": False, "error": "query_required", "results": []}

    settings = _settings()
    selected_dataset = dataset or settings["dataset"]
    cognee = _load_cognee()
    await _configure_cloud(cognee, settings)

    results = await cognee.recall(
        query,
        datasets=[selected_dataset],
        top_k=max(1, min(int(limit), 50)),
        only_context=bool(only_context),
    )
    normalized = [_normalize_hit(item) for item in list(results or [])]
    return {
        "ok": True,
        "provider": "cognee",
        "dataset": selected_dataset,
        "count": len(normalized),
        "results": normalized,
    }


async def remember(
    text: str,
    metadata: dict[str, Any] | None = None,
    dataset: str | None = None,
    self_improvement: bool = False,
) -> dict[str, Any]:
    if not text.strip():
        return {"ok": False, "error": "text_required"}

    settings = _settings()
    selected_dataset = dataset or settings["dataset"]
    cognee = _load_cognee()
    await _configure_cloud(cognee, settings)

    payload = text
    if metadata:
        payload = json.dumps(
            {"text": text, "metadata": metadata},
            ensure_ascii=False,
            default=str,
        )

    result = await cognee.remember(
        payload,
        dataset_name=selected_dataset,
        self_improvement=bool(self_improvement),
    )
    return {
        "ok": True,
        "provider": "cognee",
        "dataset": selected_dataset,
        "result": str(result),
    }


async def knowledge_graph(
    query: str,
    limit: int = 12,
    dataset: str | None = None,
) -> dict[str, Any]:
    """Graph-oriented recall surface for agents and demos.

    Cognee recall auto-routes retrieval. Returning normalized evidence keeps
    callers provider-agnostic while preserving Cognee metadata where present.
    """
    result = await memory_search(
        query=query,
        limit=limit,
        dataset=dataset,
        only_context=True,
    )
    result["capability"] = "knowledge_graph"
    return result
