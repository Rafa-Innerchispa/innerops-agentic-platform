"""Register Contífico MCP capabilities (contifico.*.v1)."""

from __future__ import annotations

from typing import Any, Callable, Dict

from inneros_core_runtime.capability_gateway import register_capability
from inneros_core_runtime import contifico_billing as bill


def _wrap(fn: Callable[..., dict[str, Any]]) -> Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]:
    def handler(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        _ = context
        return fn(**parameters)

    return handler


def _customer_create_handler(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    _ = context
    payload = parameters.get("payload") if isinstance(parameters.get("payload"), dict) else parameters
    return bill.customer_create(payload, allow_duplicate=bool(parameters.get("allow_duplicate")))


def _invoice_draft_handler(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    _ = context
    return bill.invoice_draft(
        persona_id=str(parameters.get("persona_id") or ""),
        lines=list(parameters.get("lines") or []),
        descripcion=str(parameters.get("descripcion") or ""),
        dry_run=bool(parameters.get("dry_run")),
        idempotency_key=str(parameters.get("idempotency_key") or "") or None,
    )


def _invoice_create_handler(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    ctx = context or {}
    return bill.invoice_create(
        persona_id=str(parameters.get("persona_id") or ""),
        lines=list(parameters.get("lines") or []),
        owner_approved=bool(parameters.get("owner_approved") or ctx.get("owner_approved")),
        approved_by=str(parameters.get("approved_by") or ctx.get("approved_by") or "") or None,
        idempotency_key=str(parameters.get("idempotency_key") or "") or None,
        dry_run=bool(parameters.get("dry_run")),
    )


def _manifest(
    capability_id: str,
    title: str,
    *,
    mode: str,
    risk: str,
    description: str,
    keywords: list[str],
) -> dict[str, Any]:
    return {
        "capability_id": capability_id,
        "version": "1.0.0",
        "title": title,
        "domain": "contifico",
        "risk_class": risk,
        "mode": mode,
        "description": description,
        "keywords": keywords,
        "required_scopes": ["ralfia:read"] if mode == "read_only" else ["ralfia:write"],
    }


def register_contifico_capabilities() -> None:
    Handler = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]
    specs: list[tuple[dict[str, Any], Handler]] = [
        (
            _manifest(
                "contifico.connection.status.v1",
                "Contifico connection status",
                mode="read_only",
                risk="low",
                description="API connectivity, document types, POS hint (no secrets).",
                keywords=["contifico", "connection", "status", "api"],
            ),
            bill.connection_status,
        ),
        (
            _manifest(
                "contifico.customer.search.v1",
                "Search Contifico customers",
                mode="read_only",
                risk="low",
                description="Search persona by cédula, RUC, email or name.",
                keywords=["contifico", "customer", "persona", "search"],
            ),
            bill.customer_search,
        ),
        (
            _manifest(
                "contifico.customer.get.v1",
                "Get Contifico customer",
                mode="read_only",
                risk="low",
                description="Fetch persona by persona_id.",
                keywords=["contifico", "customer", "get"],
            ),
            bill.customer_get,
        ),
        (
            _manifest(
                "contifico.customer.create.v1",
                "Create Contifico customer",
                mode="mutation",
                risk="medium",
                description="Create persona with duplicate guard.",
                keywords=["contifico", "customer", "create"],
            ),
            _customer_create_handler,
        ),
        (
            _manifest(
                "contifico.item.search.v1",
                "Search products/services",
                mode="read_only",
                risk="low",
                description="Search local catalog and live product API.",
                keywords=["contifico", "product", "item", "service"],
            ),
            bill.item_search,
        ),
        (
            _manifest(
                "contifico.invoice.draft.v1",
                "Create non-fiscal draft (COT)",
                mode="mutation",
                risk="medium",
                description="Create COT cotización borrador (electronico=false).",
                keywords=["contifico", "draft", "cot", "prefactura"],
            ),
            _invoice_draft_handler,
        ),
        (
            _manifest(
                "contifico.invoice.create.v1",
                "Create fiscal invoice (FAC)",
                mode="mutation",
                risk="high",
                description="FAC emit — requires owner approval and CONTIFICO_FISCAL_EMIT_ENABLED.",
                keywords=["contifico", "invoice", "fac", "fiscal"],
            ),
            _invoice_create_handler,
        ),
        (
            _manifest(
                "contifico.invoice.get.v1",
                "Get invoice/document",
                mode="read_only",
                risk="low",
                description="Fetch document by Contifico id.",
                keywords=["contifico", "invoice", "get"],
            ),
            bill.invoice_get,
        ),
        (
            _manifest(
                "contifico.invoice.status.v1",
                "Invoice authorization status",
                mode="read_only",
                risk="low",
                description="Document estado/autorizacion.",
                keywords=["contifico", "status", "sri"],
            ),
            bill.invoice_status,
        ),
        (
            _manifest(
                "contifico.payment.query.v1",
                "Query document cobros",
                mode="read_only",
                risk="low",
                description="List cobros linked to document.",
                keywords=["contifico", "payment", "cobro"],
            ),
            bill.payment_query,
        ),
    ]
    for manifest, handler in specs:
        if handler in (bill.connection_status, bill.customer_search, bill.customer_get, bill.item_search, bill.invoice_get, bill.invoice_status, bill.payment_query):
            register_capability(manifest, _wrap(handler))
        else:
            register_capability(manifest, handler)
