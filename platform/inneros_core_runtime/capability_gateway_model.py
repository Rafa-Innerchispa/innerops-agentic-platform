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


class _MetaGrantStoreAdapter:
    def __init__(self, ledger: Any):
        self.ledger = ledger

    def redeem_once(self, grant_id: str) -> Any:
        import time
        from datetime import datetime, timezone
        from inneros_core_runtime import meta_muse_live_dispatch
        now_epoch = time.time()
        with self.ledger._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT project_id, max_output_tokens, expires_epoch, consumed_epoch, approval_ref FROM grants WHERE id=?",
                (grant_id,),
            ).fetchone()
            if row is None:
                c.execute("ROLLBACK")
                raise meta_muse_live_dispatch.MuseDispatchError("grant_not_found")
            project_id, max_output_tokens, expires_epoch, consumed_epoch, approval_ref = row
            if consumed_epoch is not None:
                c.execute("ROLLBACK")
                raise meta_muse_live_dispatch.MuseDispatchError("grant_already_consumed")
            if expires_epoch <= now_epoch:
                c.execute("ROLLBACK")
                raise meta_muse_live_dispatch.MuseDispatchError("grant_expired")
            changed = c.execute(
                "UPDATE grants SET consumed_epoch=? WHERE id=? AND consumed_epoch IS NULL",
                (now_epoch, grant_id),
            ).rowcount
            if changed != 1:
                c.execute("ROLLBACK")
                raise meta_muse_live_dispatch.MuseDispatchError("grant_replay_rejected")
            c.execute("COMMIT")

        exp_dt = datetime.fromtimestamp(expires_epoch, tz=timezone.utc)
        return meta_muse_live_dispatch.MuseGrant(
            grant_id=grant_id,
            project_id=project_id,
            provider="meta",
            model=meta_muse_live_dispatch.MODEL,
            expires_at=exp_dt,
            max_output_tokens=max_output_tokens,
            max_prompt_chars=6000,
            max_cost_usd=0.50,
            owner_approved=bool(approval_ref),
            billing_hard_limit_verified=True,
        )


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
        effort = parameters.get("reasoning_effort")
        is_live = bool(parameters.get("live")) or parameters.get("classification") == "approved_live_dispatch"
        classification = "approved_live_dispatch" if is_live else meta_model_provider.SOURCE_POLICY
        grant = ledger.issue(
            project_id=project_id,
            prompt=prompt,
            approval=approval,
            verifier=meta_model_provider.verify_ha_owner_approval,
            classification=classification,
            max_output_tokens=max_tokens,
            ttl_seconds=ttl,
            reasoning_effort=effort,
        )
        return {"ok": True, "action": action, "grant": grant}
    elif action in ("invoke_live", "invoke_real") or (action == "invoke" and bool(parameters.get("live"))):
        from inneros_core_runtime import meta_muse_live_dispatch
        grant_id = str(parameters.get("grant_id") or "").strip()
        project_id = str(parameters.get("project_id") or context.get("project_id") or "").strip()
        prompt = str(parameters.get("prompt") or "")
        max_tokens = int(parameters.get("max_output_tokens") or 128)
        timeout = int(parameters.get("timeout_seconds") or 45)
        store = _MetaGrantStoreAdapter(ledger)
        try:
            receipt = meta_muse_live_dispatch.invoke_muse(
                prompt=prompt,
                grant_id=grant_id,
                grant_store=store,
                resolve_api_key=meta_model_provider._get_server_key,
                requested_output_tokens=max_tokens,
                timeout_seconds=timeout,
            )
            # Reconcile usage without exposing secrets
            ledger.reconcile_receipt(receipt, project_id=project_id)
            return {"ok": True, "action": action, "receipt": receipt}
        except meta_muse_live_dispatch.MuseDispatchError as exc:
            return {"ok": False, "error": str(exc), "action": action}
        except Exception as exc:
            return {"ok": False, "error": f"dispatch_failed:{type(exc).__name__}", "action": action}
    elif action == "invoke":
        grant_id = str(parameters.get("grant_id") or "").strip()
        project_id = str(parameters.get("project_id") or context.get("project_id") or "").strip()
        prompt = str(parameters.get("prompt") or "")
        effort = parameters.get("reasoning_effort")
        receipt = meta_model_provider.invoke_with_grant(
            ledger=ledger,
            grant_id=grant_id,
            project_id=project_id,
            prompt=prompt,
            reasoning_effort=effort,
        )
        return {"ok": True, "action": action, "receipt": receipt}
    elif action == "reconcile_receipt":
        receipt_data = parameters.get("receipt_data") or {}
        project_id = str(parameters.get("project_id") or context.get("project_id") or "inneros-meta-guardian-2026").strip()
        result = ledger.reconcile_receipt(receipt_data, project_id=project_id)
        return {"ok": True, "action": action, "reconciliation": result}
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
                    "action": {"type": "string", "enum": ["issue_grant", "invoke", "invoke_live", "reconcile_receipt"]},
                    "project_id": {"type": "string"},
                    "prompt": {"type": "string"},
                    "grant_id": {"type": "string"},
                    "approval": {"type": "object"},
                    "max_output_tokens": {"type": "integer"},
                    "ttl_seconds": {"type": "integer"},
                    "reasoning_effort": {"type": "string", "enum": ["low", "medium", "high"]},
                    "receipt_data": {"type": "object"},
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
