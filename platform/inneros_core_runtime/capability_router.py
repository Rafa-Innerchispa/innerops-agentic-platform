"""Deterministic tool-profile router for the RalfIA MCP catalog.

The router does not execute tools. It returns the smallest permitted profile
for a task after applying catalog, scope and risk policies.
"""

from __future__ import annotations

import re
from typing import Any

from raphiia_openai import mcp_profiles
from raphiia_openai.mcp_catalog import tool_catalog

_RISK_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

_PROFILE_SIGNALS: dict[str, tuple[str, ...]] = {
    "quoteops": ("quoteops", "misión de cotización", "mision de cotizacion", "build week"),
    "coordination": ("agente", "coordinación", "coordinacion", "tarea", "buzón", "buzon", "handoff", "lock"),
    "product_catalog": ("producto", "catálogo", "catalogo", "proveedor", "modelo", "ficha técnica", "pdf", "inventario"),
    "quoter": ("cotiz", "quote", "propuesta", "presupuesto", "pdf", "precio"),
    "vero": ("vero", "dile a vero", "facturador", "facturadora", "informe técnico", "informe tecnico"),
    "raul": ("raul", "raúl", "dile a raul", "dile a raúl", "catálogo local", "catalogo local", "hidrata catálogo"),
    "accounting": ("contable", "cuenta por", "pago", "cobro", "cheque", "factura", "accounting"),
    "communications": ("whatsapp", "correo", "email", "mensaje", "grupo", "contacto"),
    "funding": ("fondo", "funding", "grant", "crédito", "credito", "hackathon"),
    "contifico_analytics": ("contifico", "banco", "saldo", "ledger", "transacción", "transaccion"),
    "msp_core": ("cliente", "sitio", "activo", "visita", "técnico", "tecnico", "puerta", "equipo"),
}


def _select_profile(text: str) -> tuple[str, dict[str, int]]:
    normalized = re.sub(r"\s+", " ", (text or "").lower())
    scores = {
        profile: sum(1 for signal in signals if signal in normalized)
        for profile, signals in _PROFILE_SIGNALS.items()
    }
    best_score = max(scores.values(), default=0)
    if best_score == 0:
        return "msp_core", scores
    for profile in _PROFILE_SIGNALS:
        if scores[profile] == best_score:
            return profile, scores
    return "msp_core", scores


def route_tools(
    *,
    title: str,
    body: str = "",
    requested_profile: str | None = None,
    granted_scopes: list[str] | None = None,
    max_risk: str = "medium",
    tenant_id: str | None = None,
) -> dict[str, Any]:
    validation = mcp_profiles.validate_profiles()
    if not validation["ok"]:
        return {"ok": False, "error": "invalid_profile_registry", "validation": validation}

    if max_risk not in _RISK_RANK:
        return {"ok": False, "error": "invalid_max_risk", "available": sorted(_RISK_RANK)}

    scores: dict[str, int] = {}
    if requested_profile:
        profile_name = requested_profile.strip().lower()
        if profile_name not in mcp_profiles.PROFILES:
            return {
                "ok": False,
                "error": "unknown_profile",
                "available": sorted(mcp_profiles.PROFILES),
            }
        selection_reason = "explicit_profile"
    else:
        profile_name, scores = _select_profile(f"{title} {body}")
        selection_reason = "intent_signals"

    profile = mcp_profiles.get_profile(profile_name)
    if not profile.get("ok"):
        return profile

    granted = set(granted_scopes or [])
    admin = "ralfia:admin" in granted
    risk_ceiling = _RISK_RANK[max_risk]
    selected: list[str] = []
    excluded: list[dict[str, Any]] = []

    for tool_name in profile["tools"]:
        meta = tool_catalog.TOOL_DEFINITIONS.get(tool_name) or {}
        required = set(meta.get("required_scopes") or ["ralfia:read"])
        risk = str(meta.get("risk_level") or "low")
        if granted_scopes is not None and not admin and not required.issubset(granted):
            excluded.append({"tool": tool_name, "reason": "missing_scope", "required_scopes": sorted(required)})
            continue
        if _RISK_RANK.get(risk, _RISK_RANK["high"]) > risk_ceiling:
            excluded.append({"tool": tool_name, "reason": "risk_exceeds_ceiling", "risk": risk})
            continue
        selected.append(tool_name)

    return {
        "ok": True,
        "profile": profile_name,
        "selection_reason": selection_reason,
        "intent_scores": scores,
        "tenant_id": tenant_id,
        "tenant_policy": "context_only_v1",
        "max_risk": max_risk,
        "tools": selected,
        "tool_count": len(selected),
        "max_tools": profile["max_tools"],
        "excluded": excluded,
        "catalog_pin": profile["catalog_pin"],
        "profile_pin": profile["profile_pin"],
    }
