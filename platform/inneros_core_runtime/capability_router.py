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
_DEFAULT_PROFILE = "chatgpt_compact"
_MODEL_TOOL_BUDGETS = {
    "tiny": 8,
    "small": 12,
    "compact": 16,
    "voice": 12,
    "local": 16,
}

_PROFILE_SIGNALS: dict[str, tuple[str, ...]] = {
    "chatgpt_compact": ("bootstrap", "primer paso", "catalogo de tools", "catálogo de tools", "qué puedo usar", "que puedo usar"),
    "quoteops": ("quoteops", "misión de cotización", "mision de cotizacion", "build week"),
    "owner_dev": (
        "programar",
        "desarrollo",
        "developer",
        "repo",
        "github",
        "gitlab",
        "branch",
        "commit",
        "worktree",
        "pull request",
        "merge request",
        "npm",
        "pytest",
        "jest",
        "dev swarm",
        "cursor",
        "codex",
        "antigravity",
        "workforce",
    ),
    "local_self_repair": ("autorepar", "self-repair", "self repair", "reparación local", "reparacion local", "mcp roto", "runtime roto"),
    "server_ops": ("disco", "backup", "respald", "ssh", "servicio", "systemd", "puerto", "servidor", "amd", "intel"),
    "cloud_ops": ("cloudflare", "gcp", "google cloud", "cloud run", "digitalocean", "dominio", "dns", "worker", "tunnel", "tunel"),
    "local_fleet_compact": ("modelo local", "agente local", "flota local", "ahorrar creditos", "ahorrar créditos", "voz.pcdoctor"),
    "coordination": ("agente", "coordinación", "coordinacion", "tarea", "buzón", "buzon", "handoff", "lock", "a2a", "racb"),
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
        return _DEFAULT_PROFILE, scores
    for profile in _PROFILE_SIGNALS:
        if scores[profile] == best_score:
            return profile, scores
    return _DEFAULT_PROFILE, scores


def _budget_for_model(for_model: str | None) -> int | None:
    if not for_model:
        return None
    normalized = re.sub(r"[^a-z0-9_.:-]+", " ", for_model.lower())
    for token, budget in _MODEL_TOOL_BUDGETS.items():
        if token in normalized:
            return budget
    return None


def _validation_errors_for_profile(validation: dict[str, Any], profile_name: str) -> list[dict[str, Any]]:
    return [error for error in validation.get("errors", []) if error.get("profile") == profile_name]


def route_tools(
    *,
    title: str,
    body: str = "",
    requested_profile: str | None = None,
    granted_scopes: list[str] | None = None,
    max_risk: str = "medium",
    tenant_id: str | None = None,
    for_model: str | None = None,
    max_tools: int | None = None,
) -> dict[str, Any]:
    validation = mcp_profiles.validate_profiles()

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
    profile_errors = _validation_errors_for_profile(validation, profile_name)
    if profile_errors:
        return {
            "ok": False,
            "error": "invalid_selected_profile",
            "profile": profile_name,
            "validation_errors": profile_errors,
            "registry_ok": False,
        }

    requested_budget = max_tools if max_tools is not None else _budget_for_model(for_model)
    if requested_budget is not None and requested_budget <= 0:
        return {"ok": False, "error": "invalid_max_tools", "available": "positive integer"}
    tool_budget = min(int(profile["max_tools"]), int(requested_budget)) if requested_budget is not None else int(profile["max_tools"])

    granted = set(granted_scopes or [])
    admin = "ralfia:admin" in granted
    risk_ceiling = _RISK_RANK[max_risk]
    selected: list[str] = []
    excluded: list[dict[str, Any]] = []
    budget_omitted: list[str] = []

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
        if len(selected) >= tool_budget:
            budget_omitted.append(tool_name)
            continue
        selected.append(tool_name)

    if budget_omitted:
        excluded.append(
            {
                "reason": "client_tool_budget",
                "max_tools": tool_budget,
                "omitted_count": len(budget_omitted),
                "tools_sample": budget_omitted[:8],
            }
        )

    return {
        "ok": True,
        "profile": profile_name,
        "selection_reason": selection_reason,
        "intent_scores": scores,
        "tenant_id": tenant_id,
        "tenant_policy": "context_only_v1",
        "max_risk": max_risk,
        "for_model": for_model,
        "tools": selected,
        "tool_count": len(selected),
        "max_tools": tool_budget,
        "profile_max_tools": profile["max_tools"],
        "excluded": excluded,
        "catalog_pin": profile["catalog_pin"],
        "profile_pin": profile["profile_pin"],
        "registry_ok": validation["ok"],
        "registry_error_count": len(validation.get("errors", [])),
        "recommended_next_call": {
            "tool": "route_mcp_tools",
            "when": "call again with requested_profile for the next domain-specific step instead of loading the global catalog",
            "examples": ["owner_dev", "local_self_repair", "cloud_ops", "local_fleet_compact", "coordination"],
        },
    }
