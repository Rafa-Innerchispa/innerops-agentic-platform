"""Perfiles MCP versionados — proyección pequeña por dominio (Capability Router Fase 0)."""

from __future__ import annotations

from typing import Any

from raphiia_openai.capability_registry import catalog_fingerprint, log_routing_trace
from raphiia_openai.mcp_catalog import tool_catalog

PROFILES_VERSION = "1.3.0"

# Toolsets pequeños — no reemplazan tools/list global
PROFILES: dict[str, dict[str, Any]] = {
    "contifico_analytics": {
        "label": "Contífico analítico (piloto RO)",
        "model_minimum": "small",
        "max_tools": 12,
        "tools": [
            "mcp_version",
            "diagnose_mcp_session",
            "contifico_analytics_capabilities",
            "contifico_resolve_entity",
            "contifico_query",
            "contifico_get_document",
            "contifico_get_party_360",
            "contifico_explain_metric",
            "get_contifico_bank_balance",
            "contifico_inventory_summary",
        ],
    },
    "quoter": {
        "label": "Cotización + WhatsApp",
        "model_minimum": "small",
        "max_tools": 12,
        "tools": [
            "get_operational_runbooks",
            "sync_quote_sources",
            "resolve_party",
            "resolve_client",
            "create_quote_draft",
            "update_quote_draft",
            "generate_quote_intro",
            "generate_quote_pdf",
            "render_quote_document",
            "send_quote_delivery",
            "get_quote_tracking",
            "send_whatsapp_document",
        ],
    },
    "vero": {
        "label": "Vero — pipeline comercial PC Doctor",
        "model_minimum": "small",
        "max_tools": 14,
        "tools": [
            "vero_dispatch",
            "vero_proactive_briefing",
            "quote_client",
            "invoice_client",
            "technical_report_client",
            "get_commercial_mission",
            "resolve_client",
            "create_quote_draft",
            "update_quote_draft",
            "render_quote_document",
            "send_quote_delivery",
            "create_receivable_from_quote",
            "generate_supervisor_report",
            "get_quote_tracking",
            "send_whatsapp_document",
        ],
    },
    "raul": {
        "label": "Raul — catálogo local Contifico→Mongo",
        "model_minimum": "small",
        "max_tools": 8,
        "tools": [
            "raul_dispatch",
            "raul_catalog_status",
            "raul_hydrate_catalog",
            "search_inventory_catalog",
            "product_intelligence",
            "list_local_models",
            "local_model_health",
            "run_local_model",
        ],
    },
    "msp_core": {
        "label": "PC Doctor campo",
        "model_minimum": "small",
        "max_tools": 14,
        "tools": [
            "mcp_version",
            "bootstrap_context",
            "resolve_client",
            "create_client_draft",
            "upsert_client",
            "create_site_draft",
            "create_asset_draft",
            "upsert_asset",
            "create_visit_draft",
            "create_quote_draft",
            "update_quote_draft",
            "generate_quote_intro",
            "render_quote_document",
            "send_quote_delivery",
        ],
    },
    "accounting": {
        "label": "MOD-ACCOUNTING canónico",
        "model_minimum": "medium",
        "max_tools": 10,
        "tools": [
            "resolve_party",
            "create_payable_draft",
            "upsert_payable",
            "record_payment",
            "create_purchase_draft",
            "receive_goods",
            "create_receivable_draft",
            "create_receivable_from_quote",
            "accounting_summary",
            "record_collection",
        ],
    },
    "communications": {
        "label": "WhatsApp + correo",
        "model_minimum": "small",
        "max_tools": 12,
        "tools": [
            "get_whatsapp_status",
            "send_whatsapp_message",
            "send_whatsapp_document",
            "send_whatsapp_status",
            "get_whatsapp_commands_help",
            "list_whatsapp_groups",
            "resolve_whatsapp_group",
            "save_whatsapp_group",
            "get_email_archive_status",
            "search_email_archive",
            "get_email_archive_message",
            "get_operational_runbooks",
        ],
    },
    "funding": {
        "label": "Funding + credits registry",
        "model_minimum": "small",
        "max_tools": 8,
        "tools": [
            "save_funding_program",
            "list_funding_programs",
            "save_funding_application",
            "list_funding_applications",
            "save_funding_credit_account",
            "record_funding_consumption",
            "link_funding_project",
            "get_funding_registry_summary",
        ],
    },
    "contifico_read": {
        "label": "Contífico legacy read (compat)",
        "model_minimum": "medium",
        "max_tools": 14,
        "tools": [
            "get_contifico_status",
            "contifico_capabilities",
            "contifico_inventory_summary",
            "resolve_contifico_persona",
            "get_contifico_client_summary",
            "search_contifico_documents",
            "query_contifico_stats",
            "list_contifico_bank_accounts",
            "get_contifico_bank_balance",
            "search_contifico_bank_movements",
            "search_contifico_transactions",
            "get_contifico_sync_status",
            "contifico_query",
            "contifico_get_party_360",
        ],
    },
    "coordination": {
        "label": "RACB coordinación multiagente",
        "model_minimum": "small",
        "max_tools": 12,
        "tools": [
            "get_coordination_live",
            "ack_coordination_revision",
            "list_agent_messages",
            "ack_agent_message",
            "poll_agent_inbox",
            "create_agent_message",
            "list_ops_tasks",
            "create_ops_task",
            "update_ops_task_state",
            "heartbeat_ops_task",
            "complete_ops_task",
            "manage_coordination_lock",
        ],
    },
    "daily_memory": {
        "label": "Daily Life Memory privado y versionado",
        "model_minimum": "medium",
        "max_tools": 14,
        "tools": [
            "save_conversation_batch",
            "finalize_conversation",
            "save_memory",
            "update_memory",
            "search_memory",
            "get_current_state",
            "update_current_state",
            "get_person_context",
            "correct_memory",
            "forget_memory",
            "resolve_pending_item",
            "timeline",
            "get_memory_review_queue",
            "migrate_daily_memory",
        ],
    },
    "product_catalog": {
        "label": "Product Intelligence + catálogo multi-proveedor",
        "model_minimum": "medium",
        "max_tools": 5,
        "tools": [
            "product_intelligence",
            "list_inventory",
            "upsert_inventory_item",
            "resolve_party",
            "extract_fields_from_media",
        ],
    },
    "quoteops": {
        "label": "QuoteOps Build Week end-to-end",
        "model_minimum": "medium",
        "max_tools": 15,
        "tools": [
            "quoteops_start_or_continue_mission",
            "quoteops_get_mission",
            "quoteops_upsert_commercial_profile",
            "quoteops_get_sourcing_recommendations",
            "quoteops_add_supplier_offer",
            "quoteops_record_extracted_evidence",
            "quoteops_review_extracted_evidence",
            "quoteops_review_catalog_draft",
            "quoteops_update_decision_brief",
            "quoteops_upsert_configuration_alternative",
            "quoteops_review_configuration_alternative",
            "quoteops_select_package",
            "quoteops_update_quote",
            "quoteops_approve_quote",
            "quoteops_register_delivery",
        ],
    },
}


def validate_profiles() -> dict[str, Any]:
    """Validate profile contracts against the live catalog definition.

    Profiles are a public contract for small models. Publishing an unknown tool
    or exceeding ``max_tools`` silently defeats the purpose of the projection.
    """
    catalog_names = set(tool_catalog.ALL_MCP_TOOL_NAMES)
    errors: list[dict[str, Any]] = []

    for profile_name, conf in PROFILES.items():
        tools = list(conf.get("tools") or [])
        max_tools = int(conf.get("max_tools") or 0)
        duplicates = sorted({name for name in tools if tools.count(name) > 1})
        unknown = sorted(set(tools) - catalog_names)

        if max_tools <= 0:
            errors.append({"profile": profile_name, "code": "invalid_max_tools", "value": max_tools})
        if len(tools) > max_tools:
            errors.append(
                {
                    "profile": profile_name,
                    "code": "tool_limit_exceeded",
                    "tool_count": len(tools),
                    "max_tools": max_tools,
                }
            )
        if duplicates:
            errors.append({"profile": profile_name, "code": "duplicate_tools", "tools": duplicates})
        if unknown:
            errors.append({"profile": profile_name, "code": "unknown_tools", "tools": unknown})

    return {
        "ok": not errors,
        "profiles_version": PROFILES_VERSION,
        "profile_count": len(PROFILES),
        "errors": errors,
    }


def list_profiles(*, for_model: str | None = None) -> dict[str, Any]:
    fp = catalog_fingerprint()
    validation = validate_profiles()
    profiles_out = {}
    for key, conf in PROFILES.items():
        tools = list(dict.fromkeys(conf["tools"]))
        profiles_out[key] = {
            **{k: v for k, v in conf.items() if k != "tools"},
            "tools": tools,
            "tool_count": len(tools),
            "profile_pin": f"{PROFILES_VERSION}:{key}:{fp['tool_names_hash_short']}",
        }
    log_routing_trace(
        {
            "event": "list_profiles",
            "for_model": for_model,
            "profiles": list(profiles_out),
            "catalog_version": fp["catalog_version"],
        }
    )
    return {
        "ok": True,
        "profiles_version": PROFILES_VERSION,
        "catalog_version": fp["catalog_version"],
        "catalog_pin": fp["pin_hint"],
        "tool_count_global": fp["tool_count"],
        "profiles": profiles_out,
        "validation": validation,
        "note": (
            "Perfiles = proyección recomendada. El endpoint MCP legacy sigue listando todas las tools. "
            "Si diagnose_mcp_session marca stale: refrescar connector + reautorizar OAuth."
        ),
        "stale_client_guidance": {
            "if_tool_count_lt_server": "needs_refresh_connector",
            "if_catalog_version_mismatch": "needs_refresh_connector + pin catalog_pin",
            "if_oauth_errors": "needs_reauthorize_oauth",
        },
    }


def get_profile(name: str) -> dict[str, Any]:
    allp = list_profiles()
    conf = (allp.get("profiles") or {}).get(name)
    if not conf:
        return {"ok": False, "error": "unknown_profile", "available": sorted(PROFILES)}
    return {"ok": True, "profile": name, **conf, "catalog_pin": allp["catalog_pin"], "profiles_version": PROFILES_VERSION}
