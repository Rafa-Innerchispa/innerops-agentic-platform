"""Contexto web/investigación para chat owner (local-first; sin browsing silencioso)."""

from __future__ import annotations

import os
from typing import Any


def build_web_research_context(query: str) -> tuple[str, dict[str, Any]]:
    """
    Enriquece preguntas «web» con ruta AI local. No abre URLs ni scrapea sin flag explícito.
    """
    text = (query or "").strip()
    if not text:
        return "", {"ok": False, "skipped": "empty"}

    meta: dict[str, Any] = {"ok": False, "mode": "local_research"}
    try:
        from raphiia_openai import local_model_router

        classification = local_model_router.classify_task_runtime(text, task_type=None)
        meta["classification"] = {
            "task_type": classification.get("task_type"),
            "external_needed": classification.get("external_needed"),
            "local_ok": classification.get("local_ok"),
        }
        if os.getenv("OWNER_WEB_ALLOW_EXTERNAL", "0").strip().lower() in {"1", "true", "yes"} and classification.get(
            "external_needed"
        ):
            route = local_model_router.route_ai_task("Owner web query", text, task_type="research")
            meta["route"] = route
            if route.get("decision") == "execute_external":
                meta["mode"] = "external_routed_hold"
                return (
                    "INVESTIGACIÓN EXTERNA: la política marca esta pregunta como research externo. "
                    "Aún no ejecuto búsqueda en vivo automática desde Telegram; dime si autorizas "
                    "una consulta Perplexity/Gemini y la lanzo como ops task.",
                    meta | {"ok": True},
                )

        result = local_model_router.run_local_model(
            task_type="research",
            prompt=(
                "Responde en español, 4-8 frases, prudente. "
                "Si no tienes datos en vivo, dilo y da marco general útil.\n\n"
                f"Pregunta: {text}"
            ),
            max_tokens=420,
            temperature=0.35,
        )
        if result.get("ok") and (result.get("text") or result.get("response")):
            body = str(result.get("text") or result.get("response") or "").strip()
            meta.update(
                {
                    "ok": True,
                    "mode": "local_llm",
                    "model": result.get("selected_model") or result.get("model"),
                    "provider_id": result.get("provider_id"),
                }
            )
            return (
                "CONTEXTO INVESTIGACIÓN (modelo local; no es scraping en vivo):\n" + body[:1400],
                meta,
            )
        meta["error"] = result.get("error") or "local_research_failed"
    except Exception as exc:
        meta["error"] = str(exc)[:200]

    return (
        "INVESTIGACIÓN: no pude enriquecer con modelo local ahora. Responde con prudencia y pide aclarar el tema.",
        meta,
    )
