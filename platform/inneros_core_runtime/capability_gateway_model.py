"""Governed Model Inference & Frontier Provider capabilities for InnerOS."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional


def _manifest(
    capability_id: str,
    *,
    title: str,
    description: str,
    keywords: list[str],
    mode: str,
    properties: dict[str, Any],
    required: list[str],
    required_scopes: list[str],
) -> dict[str, Any]:
    return {
        "capability_id": capability_id,
        "version": "1.0.0",
        "title": title,
        "domain": "ai_inference",
        "risk_class": "medium" if mode == "mutation" else "low",
        "mode": mode,
        "description": description,
        "keywords": keywords + ["model", "provider", "inference", "tokens", "reasoning"],
        "parameters_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
        "required_scopes": required_scopes,
    }


def _provider_query_handler(parameters: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    action = str(parameters.get("action") or "list_providers").strip().lower()
    from inneros_core_runtime import meta_model_provider

    if action == "list_providers":
        from inneros_core_runtime import resource_fabric
        fab = resource_fabric.bootstrap_global_resource_fabric(dry_run=True)
        return {
            "ok": True,
            "action": action,
            "providers": fab.get("providers", []),
            "models": fab.get("models", []),
        }
    elif action == "provider_health":
        return meta_model_provider.provider_status()
    elif action == "comparison_summary":
        return meta_model_provider.get_provider_comparison_summary()
    elif action == "query_usage":
        project_id = parameters.get("project_id") or context.get("project_id")
        provider_id = parameters.get("provider_id")
        since = parameters.get("since")
        ledger = meta_model_provider.MetaGrantLedger()
        return ledger.query_usage(project_id=project_id, provider_id=provider_id, since_iso=since)
    else:
        return {"ok": False, "error": f"UNKNOWN_ACTION: {action}"}


def _frontier_reason_handler(parameters: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    action = str(parameters.get("action") or "invoke").strip().lower()
    from inneros_core_runtime import meta_model_provider
    ledger = meta_model_provider.MetaGrantLedger()

    if action == "issue_grant":
        project_id = str(parameters.get("project_id") or context.get("project_id") or "").strip()
        prompt = str(parameters.get("prompt") or "")
        approval = parameters.get("approval") or {}
        max_tokens = parameters.get("max_output_tokens", 192)
        ttl = parameters.get("ttl_seconds", 180)
        grant = ledger.issue(
            project_id=project_id,
            prompt=prompt,
            approval=approval,
            verifier=meta_model_provider.verify_ha_owner_approval,
            max_output_tokens=max_tokens,
            ttl_seconds=ttl,
        )
        return {"ok": True, "action": action, "grant": grant}
    elif action == "invoke":
        grant_id = str(parameters.get("grant_id") or "").strip()
        project_id = str(parameters.get("project_id") or context.get("project_id") or "").strip()
        prompt = str(parameters.get("prompt") or "")
        receipt = meta_model_provider.invoke_with_grant(
            ledger=ledger,
            grant_id=grant_id,
            project_id=project_id,
            prompt=prompt,
        )
        return {"ok": True, "action": action, "receipt": receipt}
    else:
        return {"ok": False, "error": f"UNKNOWN_ACTION: {action}"}


def get_model_capabilities_specs() -> list[tuple[dict[str, Any], Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]]]:
    return [
        (
            _manifest(
                "model.provider.query.v1",
                title="Query InnerOS model providers and health",
                description="List available local and external providers, verify health and owner vault configuration, and query usage summaries.",
                keywords=["query", "providers", "models", "health", "usage"],
                mode="read_only",
                properties={
                    "action": {
                        "type": "string",
                        "enum": ["list_providers", "provider_health", "comparison_summary", "query_usage"],
                    },
                    "project_id": {"type": "string"},
                    "provider_id": {"type": "string"},
                    "since": {"type": "string"},
                },
                required=["action"],
                required_scopes=["ralfia:read"],
            ),
            _provider_query_handler,
        ),
        (
            _manifest(
                "model.frontier.reason.v1",
                title="Governed frontier model reasoning dispatch",
                description="Issue owner-authorized single-use grants and execute authorized reasoning requests without exposing API credentials.",
                keywords=["frontier", "reason", "meta", "grant", "invoke"],
                mode="mutation",
                properties={
                    "action": {"type": "string", "enum": ["issue_grant", "invoke"]},
                    "project_id": {"type": "string"},
                    "prompt": {"type": "string"},
                    "grant_id": {"type": "string"},
                    "approval": {"type": "object"},
                    "max_output_tokens": {"type": "integer"},
                    "ttl_seconds": {"type": "integer"},
                },
                required=["action"],
                required_scopes=["ralfia:agents"],
            ),
            _frontier_reason_handler,
        ),
    ]


def register_model_frontier_capabilities(register_fn: Optional[Callable[..., Any]] = None) -> int:
    fn = register_fn
    if fn is None:
        try:
            from inneros_core_runtime.capability_gateway import register_capability
            fn = register_capability
        except Exception:
            fn = None
    specs = get_model_capabilities_specs()
    if fn:
        for manifest, handler in specs:
            fn(manifest, handler)
    return len(specs)
