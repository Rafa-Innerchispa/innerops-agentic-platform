"""MOD-ACCOUNTING — cuentas por pagar (AP), pagos y alertas."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId

from raphiia_openai import mongo_store
from raphiia_openai.operational.audit import log_ops_action
from raphiia_openai.operational.constants import (
    COL_ACCOUNTING_PAYABLES,
    COL_ACCOUNTING_PAYMENTS,
    COL_ACCOUNTING_RECEIVABLES,
)
from raphiia_openai.operational import party_store

ALLOWED_PAYABLE_STATUS = {
    "draft",
    "pending_review",
    "approved",
    "scheduled",
    "paid",
    "cancelled",
    "rejected",
}
ALLOWED_PAYABLE_TYPES = {"check", "invoice", "transfer", "other"}
ALLOWED_PAYMENT_METHODS = {"check", "transfer", "bank_transfer", "cash", "card", "other"}
NON_CANONICAL_PAYABLE_STATUSES = ("draft", "promoted")

ALLOWED_RECEIVABLE_STATUS = {"draft", "pending", "sent", "partial", "paid", "cancelled", "written_off"}
NON_CANONICAL_RECEIVABLE_STATUSES = ("draft", "promoted")

PAYABLE_SEARCH_FIELDS = (
    "payable_id",
    "draft_id",
    "party_id",
    "supplier_name",
    "tax_id",
    "check_number",
    "invoice_number",
    "reference",
    "notes",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    return mongo_store.get_db()


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _pull(payload: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return default


def _serialize(doc: dict[str, Any] | None) -> dict[str, Any]:
    if not doc:
        return {}
    out = dict(doc)
    if "_id" in out:
        out["_id"] = str(out["_id"])
    return out


def _new_id(prefix: str) -> str:
    return f"{prefix}_{ObjectId()}"


def _amount(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _normalize_key(value: Any) -> str:
    return re.sub(r"\s+", " ", _norm(value)).strip().lower()


def _payable_dedupe_key(doc: dict[str, Any]) -> str:
    party_id = _norm(_pull(doc, "party_id", "supplier_party_id"))
    tax_id = _norm(_pull(doc, "tax_id", "ruc", "supplier_tax_id"))
    supplier_name = _normalize_key(_pull(doc, "supplier_name", "payee_name"))
    check_number = _norm(_pull(doc, "check_number", "cheque_number"))
    invoice_number = _norm(_pull(doc, "invoice_number", "factura"))
    reference = _norm(_pull(doc, "reference", "ref"))
    due_date = _norm(_pull(doc, "due_date"))
    amount = _amount(_pull(doc, "amount", "total", default=0))
    if party_id and check_number:
        return f"party:{party_id}::check:{check_number}"
    if tax_id and check_number:
        return f"tax:{tax_id}::check:{check_number}"
    if party_id and invoice_number:
        return f"party:{party_id}::inv:{invoice_number}"
    if tax_id and invoice_number:
        return f"tax:{tax_id}::inv:{invoice_number}"
    if party_id and reference:
        return f"party:{party_id}::ref:{reference}"
    if supplier_name and check_number:
        return f"name:{supplier_name}::check:{check_number}"
    if party_id and due_date and amount:
        return f"party:{party_id}::due:{due_date}::amt:{amount:.2f}"
    if tax_id and due_date and amount:
        return f"tax:{tax_id}::due:{due_date}::amt:{amount:.2f}"
    return ""


def _ensure_accounting_indexes() -> None:
    db = _db()
    specs = [
        (COL_ACCOUNTING_PAYABLES, [("payable_id", 1)], {"name": "ux_acct_payables_id", "unique": True, "sparse": True}),
        (COL_ACCOUNTING_PAYABLES, [("draft_id", 1)], {"name": "ux_acct_payables_draft", "unique": True, "sparse": True}),
        (COL_ACCOUNTING_PAYABLES, [("dedupe_key", 1)], {
            "name": "ux_acct_payables_dedupe",
            "unique": True,
            "sparse": True,
            "partialFilterExpression": {"dedupe_key": {"$type": "string", "$ne": ""}},
        }),
        (COL_ACCOUNTING_PAYABLES, [("entity_id", 1), ("status", 1), ("due_date", 1)], {"name": "ix_acct_payables_entity_due"}),
        (COL_ACCOUNTING_PAYMENTS, [("payment_id", 1)], {"name": "ux_acct_payments_id", "unique": True, "sparse": True}),
        (COL_ACCOUNTING_PAYMENTS, [("payable_id", 1)], {"name": "ix_acct_payments_payable"}),
        (COL_ACCOUNTING_RECEIVABLES, [("receivable_id", 1)], {"name": "ux_acct_receivables_id", "unique": True, "sparse": True}),
        (COL_ACCOUNTING_RECEIVABLES, [("draft_id", 1)], {"name": "ux_acct_receivables_draft", "unique": True, "sparse": True}),
        (COL_ACCOUNTING_RECEIVABLES, [("dedupe_key", 1)], {
            "name": "ux_acct_receivables_dedupe",
            "unique": True,
            "sparse": True,
            "partialFilterExpression": {"dedupe_key": {"$type": "string", "$ne": ""}},
        }),
        (COL_ACCOUNTING_RECEIVABLES, [("entity_id", 1), ("status", 1), ("due_date", 1)], {"name": "ix_acct_receivables_entity_due"}),
    ]
    for collection, keys, kwargs in specs:
        try:
            db[collection].create_index(keys, **kwargs)
        except Exception:
            continue


def _resolve_supplier_party(payload: dict[str, Any]) -> tuple[str, str]:
    party_id = _norm(_pull(payload, "party_id", "supplier_party_id"))
    supplier_name = _norm(_pull(payload, "supplier_name", "payee_name", "nombre"))
    tax_id = _norm(_pull(payload, "tax_id", "ruc", "supplier_tax_id"))
    if party_id:
        return party_id, supplier_name
    query = tax_id or supplier_name
    if query:
        match = party_store.resolve_party(query, limit=1, roles=["supplier"]).get("best_match") or {}
        if not match and tax_id:
            match = party_store.resolve_party(tax_id, limit=1).get("best_match") or {}
        if match:
            return _norm(match.get("party_id")), _norm(match.get("display_name") or supplier_name)
    return party_id, supplier_name


def _find_reusable_payable(dedupe_key: str) -> tuple[str, dict[str, Any]] | None:
    if not dedupe_key:
        return None
    db = _db()
    draft = db[COL_ACCOUNTING_PAYABLES].find_one({"dedupe_key": dedupe_key, "status": "draft"})
    if draft:
        return "draft", _serialize(draft)
    canonical = db[COL_ACCOUNTING_PAYABLES].find_one(
        {"dedupe_key": dedupe_key, "status": {"$nin": list(NON_CANONICAL_PAYABLE_STATUSES)}}
    )
    if canonical:
        return "canonical", _serialize(canonical)
    return None


def create_payable_draft(payload: dict[str, Any]) -> dict[str, Any]:
    party_id, supplier_name = _resolve_supplier_party(payload)
    preview = {
        "party_id": party_id,
        "supplier_name": supplier_name or _norm(_pull(payload, "supplier_name")),
        "tax_id": _norm(_pull(payload, "tax_id", "ruc")),
        "entity_id": _norm(_pull(payload, "entity_id", default="ent_pcdoctor")),
        "payable_type": _norm(_pull(payload, "payable_type", "type", default="check")),
        "check_number": _norm(_pull(payload, "check_number", "cheque_number")),
        "invoice_number": _norm(_pull(payload, "invoice_number")),
        "reference": _norm(_pull(payload, "reference")),
        "amount": _amount(_pull(payload, "amount", "total")),
        "currency": _norm(_pull(payload, "currency", default="USD")),
        "due_date": _norm(_pull(payload, "due_date")),
    }
    dedupe_key = _payable_dedupe_key({**preview, **payload})
    reusable = _find_reusable_payable(dedupe_key)
    if reusable:
        reused_from, existing = reusable
        out: dict[str, Any] = {
            "ok": True,
            "reused": True,
            "reused_from": reused_from,
            "draft_id": existing.get("draft_id"),
            "payable_draft": existing,
        }
        if reused_from == "canonical":
            out["payable_id"] = existing.get("payable_id")
            out["payable"] = existing
        return out
    draft_id = _new_id("payabledraft")
    now = _now_iso()
    doc = {
        **preview,
        "draft_id": draft_id,
        "status": "draft",
        "issue_date": _norm(_pull(payload, "issue_date")),
        "bank_name": _norm(_pull(payload, "bank_name")),
        "account_number": _norm(_pull(payload, "account_number")),
        "ocr_text": _norm(_pull(payload, "ocr_text")),
        "media_id": _norm(_pull(payload, "media_id")),
        "media_url": _norm(_pull(payload, "media_url")),
        "quote_id": _norm(_pull(payload, "quote_id")),
        "project_ref": _norm(_pull(payload, "project_ref")),
        "notes": _norm(_pull(payload, "notes")),
        "tags": payload.get("tags") or [],
        "source": _norm(_pull(payload, "source", default="chatgpt_mcp")),
        "captured_by": _norm(_pull(payload, "captured_by", default="CHATGPT")),
        "dedupe_key": dedupe_key,
        "created_at": now,
        "updated_at": now,
    }
    if doc["payable_type"] not in ALLOWED_PAYABLE_TYPES:
        doc["payable_type"] = "check"
    if not dedupe_key:
        doc.pop("dedupe_key", None)
    db = _db()
    db[COL_ACCOUNTING_PAYABLES].insert_one(doc)
    log_ops_action(
        actor="CHATGPT",
        action="create_payable_draft",
        resource_type="payable_draft",
        resource_id=draft_id,
        summary=f"Payable draft {doc.get('supplier_name') or doc.get('check_number') or draft_id}",
        tool_used="create_payable_draft",
        metadata={"party_id": party_id, "amount": doc["amount"], "due_date": doc["due_date"]},
    )
    return {"ok": True, "reused": False, "draft_id": draft_id, "payable_draft": _serialize(doc)}


def upsert_payable(payload: dict[str, Any]) -> dict[str, Any]:
    db = _db()
    now = _now_iso()
    draft_id = _norm(_pull(payload, "payable_draft_id", "draft_id"))
    draft = db[COL_ACCOUNTING_PAYABLES].find_one({"draft_id": draft_id}) if draft_id else None
    merged = {**(draft or {}), **payload}
    payable_id = _norm(_pull(merged, "payable_id")) or _new_id("payable")
    party_id, supplier_name = _resolve_supplier_party(merged)
    existing = db[COL_ACCOUNTING_PAYABLES].find_one({"payable_id": payable_id})
    if not existing and draft_id:
        existing = draft
    if not existing:
        dedupe_key = _payable_dedupe_key(merged)
        if dedupe_key:
            existing = db[COL_ACCOUNTING_PAYABLES].find_one(
                {"dedupe_key": dedupe_key, "status": {"$nin": list(NON_CANONICAL_PAYABLE_STATUSES)}}
            )
    status = _norm(_pull(merged, "status", default=(existing or {}).get("status") or "pending_review"))
    if status not in ALLOWED_PAYABLE_STATUS:
        status = "pending_review"
    doc = {
        "payable_id": payable_id,
        "party_id": party_id or _norm((existing or {}).get("party_id")),
        "supplier_name": supplier_name or _norm(_pull(merged, "supplier_name")) or (existing or {}).get("supplier_name", ""),
        "tax_id": _norm(_pull(merged, "tax_id", "ruc")) or (existing or {}).get("tax_id", ""),
        "entity_id": _norm(_pull(merged, "entity_id")) or (existing or {}).get("entity_id") or "ent_pcdoctor",
        "payable_type": _norm(_pull(merged, "payable_type", default=(existing or {}).get("payable_type") or "check")),
        "check_number": _norm(_pull(merged, "check_number")) or (existing or {}).get("check_number", ""),
        "invoice_number": _norm(_pull(merged, "invoice_number")) or (existing or {}).get("invoice_number", ""),
        "reference": _norm(_pull(merged, "reference")) or (existing or {}).get("reference", ""),
        "amount": _amount(_pull(merged, "amount")) or _amount((existing or {}).get("amount")),
        "currency": _norm(_pull(merged, "currency", default=(existing or {}).get("currency") or "USD")),
        "issue_date": _norm(_pull(merged, "issue_date")) or (existing or {}).get("issue_date", ""),
        "due_date": _norm(_pull(merged, "due_date")) or (existing or {}).get("due_date", ""),
        "bank_name": _norm(_pull(merged, "bank_name")) or (existing or {}).get("bank_name", ""),
        "account_number": _norm(_pull(merged, "account_number")) or (existing or {}).get("account_number", ""),
        "ocr_text": _norm(_pull(merged, "ocr_text")) or (existing or {}).get("ocr_text", ""),
        "media_id": _norm(_pull(merged, "media_id")) or (existing or {}).get("media_id", ""),
        "media_url": _norm(_pull(merged, "media_url")) or (existing or {}).get("media_url", ""),
        "quote_id": _norm(_pull(merged, "quote_id")) or (existing or {}).get("quote_id", ""),
        "project_ref": _norm(_pull(merged, "project_ref")) or (existing or {}).get("project_ref", ""),
        "notes": _norm(_pull(merged, "notes")) or (existing or {}).get("notes", ""),
        "tags": merged.get("tags") or (existing or {}).get("tags") or [],
        "status": status,
        "approved_by": _norm(_pull(merged, "approved_by")) or (existing or {}).get("approved_by", ""),
        "approved_at": _norm(_pull(merged, "approved_at")) or (existing or {}).get("approved_at", ""),
        "source": _norm(_pull(merged, "source", default=(existing or {}).get("source") or "chatgpt_mcp")),
        "dedupe_key": _payable_dedupe_key({**dict(existing or {}), **merged}),
        "updated_at": now,
    }
    created = False
    if not existing or existing.get("status") == "draft":
        if not existing:
            doc["created_at"] = now
            db[COL_ACCOUNTING_PAYABLES].insert_one(doc)
            created = True
        else:
            db[COL_ACCOUNTING_PAYABLES].update_one({"_id": existing["_id"]}, {"$set": doc})
    else:
        db[COL_ACCOUNTING_PAYABLES].update_one({"payable_id": payable_id}, {"$set": doc})
    if draft_id:
        db[COL_ACCOUNTING_PAYABLES].update_one(
            {"draft_id": draft_id},
            {"$set": {"status": "promoted", "payable_id": payable_id, "updated_at": now}},
        )
    saved = _serialize(db[COL_ACCOUNTING_PAYABLES].find_one({"payable_id": payable_id}))
    log_ops_action(
        actor="CHATGPT",
        action="upsert_payable",
        resource_type="payable",
        resource_id=payable_id,
        summary=f"Payable {saved.get('supplier_name') or payable_id} {saved.get('amount')}",
        tool_used="upsert_payable",
        metadata={"created": created, "status": saved.get("status"), "party_id": saved.get("party_id")},
    )
    return {"ok": True, "created": created, "payable_id": payable_id, "payable": saved}


def resolve_payable(identifier: str, limit: int = 10) -> dict[str, Any]:
    db = _db()
    raw = _norm(identifier)
    if not raw:
        return {"ok": True, "count": 0, "matches": [], "best_match": None}
    or_filters = [{field: {"$regex": re.escape(raw), "$options": "i"}} for field in PAYABLE_SEARCH_FIELDS]
    cursor = db[COL_ACCOUNTING_PAYABLES].find({"$or": or_filters}).sort("updated_at", -1).limit(max(1, min(limit, 50)))
    matches = [_serialize(doc) for doc in cursor]
    return {"ok": True, "count": len(matches), "matches": matches, "best_match": matches[0] if matches else None}


def list_payables_due(
    entity_id: str | None = None,
    days_ahead: int = 14,
    limit: int = 50,
    status: str | None = None,
) -> dict[str, Any]:
    db = _db()
    now = datetime.now(timezone.utc)
    horizon = (now + timedelta(days=max(1, days_ahead))).date().isoformat()
    today = now.date().isoformat()
    query: dict[str, Any] = {
        "status": {"$in": ["approved", "scheduled", "pending_review"]},
        "due_date": {"$lte": horizon, "$ne": ""},
    }
    if entity_id:
        query["entity_id"] = _norm(entity_id)
    if status:
        query["status"] = _norm(status)
    cursor = db[COL_ACCOUNTING_PAYABLES].find(query).sort("due_date", 1).limit(max(1, min(limit, 100)))
    items = [_serialize(doc) for doc in cursor]
    overdue = [i for i in items if _norm(i.get("due_date")) and _norm(i.get("due_date")) < today]
    due_soon = [i for i in items if i not in overdue]
    return {
        "ok": True,
        "count": len(items),
        "overdue_count": len(overdue),
        "due_soon_count": len(due_soon),
        "payables": items,
        "overdue": overdue,
        "due_soon": due_soon,
        "horizon_days": days_ahead,
        "entity_id": entity_id,
    }


def record_payment(payload: dict[str, Any]) -> dict[str, Any]:
    db = _db()
    now = _now_iso()
    payable_id = _norm(_pull(payload, "payable_id"))
    if not payable_id:
        return {"ok": False, "error": "payable_id required"}
    payable = db[COL_ACCOUNTING_PAYABLES].find_one({"payable_id": payable_id})
    if not payable:
        return {"ok": False, "error": f"payable_not_found: {payable_id}"}
    payment_id = _norm(_pull(payload, "payment_id")) or _new_id("payment")
    amount = _amount(_pull(payload, "amount")) or _amount(payable.get("amount"))
    method = _norm(_pull(payload, "method", "payment_method", default="check"))
    if method not in ALLOWED_PAYMENT_METHODS:
        method = "check"
    payment_doc = {
        "payment_id": payment_id,
        "payable_id": payable_id,
        "party_id": _norm(payable.get("party_id")),
        "entity_id": _norm(payable.get("entity_id")),
        "amount": amount,
        "currency": _norm(_pull(payload, "currency", default=payable.get("currency") or "USD")),
        "method": method,
        "paid_at": _norm(_pull(payload, "paid_at", default=now)),
        "reference": _norm(_pull(payload, "reference", "check_number")),
        "bank_name": _norm(_pull(payload, "bank_name")) or _norm(payable.get("bank_name")),
        "notes": _norm(_pull(payload, "notes")),
        "recorded_by": _norm(_pull(payload, "recorded_by", default="CHATGPT")),
        "source": _norm(_pull(payload, "source", default="chatgpt_mcp")),
        "created_at": now,
        "updated_at": now,
    }
    db[COL_ACCOUNTING_PAYMENTS].insert_one(payment_doc)
    db[COL_ACCOUNTING_PAYABLES].update_one(
        {"payable_id": payable_id},
        {"$set": {"status": "paid", "paid_at": payment_doc["paid_at"], "payment_id": payment_id, "updated_at": now}},
    )
    saved_payable = _serialize(db[COL_ACCOUNTING_PAYABLES].find_one({"payable_id": payable_id}))
    log_ops_action(
        actor="CHATGPT",
        action="record_payment",
        resource_type="payment",
        resource_id=payment_id,
        summary=f"Payment {amount} for {payable_id}",
        tool_used="record_payment",
        metadata={"payable_id": payable_id, "method": method},
    )
    inventory_result = None
    if payload.get("receive_inventory") or payable.get("purchase_id") or payload.get("purchase_id"):
        from raphiia_openai.operational import inventory_store

        inventory_result = inventory_store.receive_goods({
            "purchase_id": _norm(_pull(payload, "purchase_id")) or _norm(payable.get("purchase_id")),
            "payable_id": payable_id,
            "entity_id": _norm(payable.get("entity_id")),
            "notes": "auto_receive_on_payment",
        })
    out = {
        "ok": True,
        "payment_id": payment_id,
        "payment": _serialize(payment_doc),
        "payable": saved_payable,
    }
    if inventory_result:
        out["inventory"] = inventory_result
    return out


def accounting_summary(entity_id: str | None = None, period: str | None = None) -> dict[str, Any]:
    db = _db()
    query: dict[str, Any] = {}
    if entity_id:
        query["entity_id"] = _norm(entity_id)
    payables = list(db[COL_ACCOUNTING_PAYABLES].find(query))
    payments = list(db[COL_ACCOUNTING_PAYMENTS].find(query))
    receivables = list(db[COL_ACCOUNTING_RECEIVABLES].find(query))
    open_statuses = {"draft", "pending_review", "approved", "scheduled"}
    open_ap = [p for p in payables if _norm(p.get("status")) in open_statuses]
    paid_ap = [p for p in payables if _norm(p.get("status")) == "paid"]
    open_ar = [r for r in receivables if _norm(r.get("status")) in {"pending", "sent", "partial"}]
    paid_ar = [r for r in receivables if _norm(r.get("status")) == "paid"]
    total_open = round(sum(_amount(p.get("amount")) for p in open_ap), 2)
    total_paid = round(sum(_amount(p.get("amount")) for p in paid_ap), 2)
    total_payments = round(sum(_amount(p.get("amount")) for p in payments), 2)
    ar_open_total = round(
        sum(_amount(r.get("amount")) - _amount(r.get("amount_collected")) for r in open_ar), 2
    )
    ar_paid_total = round(sum(_amount(r.get("amount_collected")) for r in paid_ar), 2)
    return {
        "ok": True,
        "entity_id": entity_id,
        "period": period,
        "ap_open_count": len(open_ap),
        "ap_open_total": total_open,
        "ap_paid_count": len(paid_ap),
        "ap_paid_total": total_paid,
        "ar_open_count": len(open_ar),
        "ar_open_total": ar_open_total,
        "ar_paid_count": len(paid_ar),
        "ar_collected_total": ar_paid_total,
        "payments_count": len(payments),
        "payments_total": total_payments,
        "net_position": round(ar_open_total - total_open, 2),
        "module": "MOD-ACCOUNTING",
        "phase": "AP_AR_v2",
    }


def _names_compatible(a: str, b: str) -> bool:
    na = re.sub(r"\s+", " ", (a or "").strip().lower())
    nb = re.sub(r"\s+", " ", (b or "").strip().lower())
    if not na or not nb:
        return False
    if na == nb:
        return True
    if len(na) >= 4 and na in nb:
        return True
    if len(nb) >= 4 and nb in na:
        return True
    # token overlap ≥ 50%
    ta, tb = set(na.split()), set(nb.split())
    if not ta or not tb:
        return False
    return len(ta & tb) / max(len(ta), len(tb)) >= 0.5


def _resolve_client_party(payload: dict[str, Any]) -> tuple[str, str]:
    party_id = _norm(_pull(payload, "party_id", "client_party_id"))
    client_name = _norm(_pull(payload, "client_name", "customer_name", "display_name"))
    tax_id = _norm(_pull(payload, "tax_id", "ruc", "client_tax_id"))
    if party_id:
        return party_id, client_name
    # Prefer tax_id exact resolve; never overwrite an explicit client_name with a weak fuzzy hit
    if tax_id:
        match = party_store.resolve_party(tax_id, limit=1, roles=["client"]).get("best_match") or {}
        if not match:
            match = party_store.resolve_party(tax_id, limit=1).get("best_match") or {}
        if match and (
            _norm(match.get("tax_id")) == tax_id
            or _names_compatible(client_name, _norm(match.get("display_name") or match.get("legal_name")))
        ):
            return _norm(match.get("party_id")), _norm(match.get("display_name") or client_name)
    if client_name:
        match = party_store.resolve_party(client_name, limit=1, roles=["client"]).get("best_match") or {}
        if match and _names_compatible(client_name, _norm(match.get("display_name") or match.get("legal_name"))):
            return _norm(match.get("party_id")), _norm(match.get("display_name") or client_name)
        # Keep explicit name; do not adopt unrelated party
        return "", client_name
    return party_id, client_name


def _receivable_dedupe_key(doc: dict[str, Any]) -> str:
    party_id = _norm(_pull(doc, "party_id", "client_party_id"))
    tax_id = _norm(_pull(doc, "tax_id", "ruc"))
    quote_id = _norm(_pull(doc, "quote_id"))
    invoice_number = _norm(_pull(doc, "invoice_number"))
    reference = _norm(_pull(doc, "reference"))
    due_date = _norm(_pull(doc, "due_date"))
    amount = _amount(_pull(doc, "amount", "total", default=0))
    if quote_id:
        return f"quote:{quote_id}"
    if party_id and invoice_number:
        return f"party:{party_id}::inv:{invoice_number}"
    if tax_id and invoice_number:
        return f"tax:{tax_id}::inv:{invoice_number}"
    if party_id and reference:
        return f"party:{party_id}::ref:{reference}"
    if party_id and due_date and amount:
        return f"party:{party_id}::due:{due_date}::amt:{amount:.2f}"
    return ""


def _find_reusable_receivable(dedupe_key: str) -> tuple[str, dict[str, Any]] | None:
    if not dedupe_key:
        return None
    db = _db()
    draft = db[COL_ACCOUNTING_RECEIVABLES].find_one({"dedupe_key": dedupe_key, "status": "draft"})
    if draft:
        return "draft", _serialize(draft)
    canonical = db[COL_ACCOUNTING_RECEIVABLES].find_one(
        {"dedupe_key": dedupe_key, "status": {"$nin": list(NON_CANONICAL_RECEIVABLE_STATUSES)}}
    )
    if canonical:
        return "canonical", _serialize(canonical)
    return None


def create_receivable_draft(payload: dict[str, Any]) -> dict[str, Any]:
    party_id, client_name = _resolve_client_party(payload)
    preview = {
        "party_id": party_id,
        "client_name": client_name or _norm(_pull(payload, "client_name")),
        "tax_id": _norm(_pull(payload, "tax_id", "ruc")),
        "entity_id": _norm(_pull(payload, "entity_id", default="ent_pcdoctor")),
        "quote_id": _norm(_pull(payload, "quote_id")),
        "invoice_number": _norm(_pull(payload, "invoice_number")),
        "reference": _norm(_pull(payload, "reference")),
        "amount": _amount(_pull(payload, "amount", "total")),
        "currency": _norm(_pull(payload, "currency", default="USD")),
        "due_date": _norm(_pull(payload, "due_date")),
    }
    dedupe_key = _receivable_dedupe_key({**preview, **payload})
    reusable = _find_reusable_receivable(dedupe_key)
    if reusable:
        reused_from, existing = reusable
        # Corregir contaminación de identidad en drafts reutilizados
        desired_name = client_name or _norm(_pull(payload, "client_name"))
        if desired_name and _norm(existing.get("client_name")) != desired_name:
            filt = {"draft_id": existing.get("draft_id")} if existing.get("draft_id") else {"quote_id": preview["quote_id"]}
            _db()[COL_ACCOUNTING_RECEIVABLES].update_one(
                filt,
                {"$set": {
                    "client_name": desired_name,
                    "party_id": party_id or existing.get("party_id", ""),
                    "tax_id": preview["tax_id"] or existing.get("tax_id", ""),
                    "updated_at": _now_iso(),
                }},
            )
            refreshed = _db()[COL_ACCOUNTING_RECEIVABLES].find_one(filt) or existing
            existing = _serialize(refreshed) if isinstance(refreshed, dict) else existing
            existing["client_name"] = desired_name
        out: dict[str, Any] = {
            "ok": True,
            "reused": True,
            "reused_from": reused_from,
            "draft_id": existing.get("draft_id"),
            "receivable_draft": existing,
        }
        if reused_from == "canonical":
            out["receivable_id"] = existing.get("receivable_id")
            out["receivable"] = existing
        return out
    draft_id = _new_id("receivabledraft")
    now = _now_iso()
    doc = {
        **preview,
        "draft_id": draft_id,
        "status": "draft",
        "issue_date": _norm(_pull(payload, "issue_date")),
        "notes": _norm(_pull(payload, "notes")),
        "tags": payload.get("tags") or [],
        "source": _norm(_pull(payload, "source", default="chatgpt_mcp")),
        "captured_by": _norm(_pull(payload, "captured_by", default="CHATGPT")),
        "dedupe_key": dedupe_key,
        "created_at": now,
        "updated_at": now,
    }
    if not dedupe_key:
        doc.pop("dedupe_key", None)
    _db()[COL_ACCOUNTING_RECEIVABLES].insert_one(doc)
    log_ops_action(
        actor="CHATGPT",
        action="create_receivable_draft",
        resource_type="receivable_draft",
        resource_id=draft_id,
        summary=f"Receivable draft {client_name or quote_id or draft_id}",
        tool_used="create_receivable_draft",
        metadata={"party_id": party_id, "amount": doc["amount"], "quote_id": doc["quote_id"]},
    )
    return {"ok": True, "reused": False, "draft_id": draft_id, "receivable_draft": _serialize(doc)}


def upsert_receivable(payload: dict[str, Any]) -> dict[str, Any]:
    db = _db()
    now = _now_iso()
    draft_id = _norm(_pull(payload, "receivable_draft_id", "draft_id"))
    draft = db[COL_ACCOUNTING_RECEIVABLES].find_one({"draft_id": draft_id}) if draft_id else None
    merged = {**(draft or {}), **payload}
    receivable_id = _norm(_pull(merged, "receivable_id")) or _new_id("receivable")
    party_id, client_name = _resolve_client_party(merged)
    existing = db[COL_ACCOUNTING_RECEIVABLES].find_one({"receivable_id": receivable_id})
    if not existing and draft_id:
        existing = draft
    if not existing:
        dk = _receivable_dedupe_key(merged)
        if dk:
            existing = db[COL_ACCOUNTING_RECEIVABLES].find_one(
                {"dedupe_key": dk, "status": {"$nin": list(NON_CANONICAL_RECEIVABLE_STATUSES)}}
            )
    status = _norm(_pull(merged, "status", default=(existing or {}).get("status") or "pending"))
    if status not in ALLOWED_RECEIVABLE_STATUS:
        status = "pending"
    doc = {
        "receivable_id": receivable_id,
        "party_id": party_id or _norm((existing or {}).get("party_id")),
        "client_name": client_name or _norm(_pull(merged, "client_name")) or (existing or {}).get("client_name", ""),
        "tax_id": _norm(_pull(merged, "tax_id")) or (existing or {}).get("tax_id", ""),
        "entity_id": _norm(_pull(merged, "entity_id")) or (existing or {}).get("entity_id") or "ent_pcdoctor",
        "quote_id": _norm(_pull(merged, "quote_id")) or (existing or {}).get("quote_id", ""),
        "invoice_number": _norm(_pull(merged, "invoice_number")) or (existing or {}).get("invoice_number", ""),
        "reference": _norm(_pull(merged, "reference")) or (existing or {}).get("reference", ""),
        "amount": _amount(_pull(merged, "amount")) or _amount((existing or {}).get("amount")),
        "amount_collected": _amount(_pull(merged, "amount_collected", default=(existing or {}).get("amount_collected"))),
        "currency": _norm(_pull(merged, "currency", default=(existing or {}).get("currency") or "USD")),
        "issue_date": _norm(_pull(merged, "issue_date")) or (existing or {}).get("issue_date", ""),
        "due_date": _norm(_pull(merged, "due_date")) or (existing or {}).get("due_date", ""),
        "notes": _norm(_pull(merged, "notes")) or (existing or {}).get("notes", ""),
        "status": status,
        "source": _norm(_pull(merged, "source", default=(existing or {}).get("source") or "chatgpt_mcp")),
        "dedupe_key": _receivable_dedupe_key({**dict(existing or {}), **merged}),
        "updated_at": now,
    }
    created = False
    if not existing or existing.get("status") == "draft":
        if not existing:
            doc["created_at"] = now
            db[COL_ACCOUNTING_RECEIVABLES].insert_one(doc)
            created = True
        else:
            db[COL_ACCOUNTING_RECEIVABLES].update_one({"_id": existing["_id"]}, {"$set": doc})
    else:
        db[COL_ACCOUNTING_RECEIVABLES].update_one({"receivable_id": receivable_id}, {"$set": doc})
    if draft_id:
        db[COL_ACCOUNTING_RECEIVABLES].update_one(
            {"draft_id": draft_id},
            {"$set": {"status": "promoted", "receivable_id": receivable_id, "updated_at": now}},
        )
    saved = _serialize(db[COL_ACCOUNTING_RECEIVABLES].find_one({"receivable_id": receivable_id}))
    log_ops_action(
        actor="CHATGPT",
        action="upsert_receivable",
        resource_type="receivable",
        resource_id=receivable_id,
        summary=f"Receivable {saved.get('client_name') or receivable_id}",
        tool_used="upsert_receivable",
        metadata={"created": created, "status": saved.get("status"), "quote_id": saved.get("quote_id")},
    )
    return {"ok": True, "created": created, "receivable_id": receivable_id, "receivable": saved}


def list_receivables_open(entity_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    db = _db()
    query: dict[str, Any] = {"status": {"$in": ["pending", "sent", "partial"]}}
    if entity_id:
        query["entity_id"] = _norm(entity_id)
    cursor = db[COL_ACCOUNTING_RECEIVABLES].find(query).sort("due_date", 1).limit(max(1, min(limit, 100)))
    items = [_serialize(doc) for doc in cursor]
    total = round(sum(_amount(i.get("amount")) - _amount(i.get("amount_collected")) for i in items), 2)
    return {"ok": True, "count": len(items), "open_total": total, "receivables": items}


def record_collection(payload: dict[str, Any]) -> dict[str, Any]:
    db = _db()
    now = _now_iso()
    receivable_id = _norm(_pull(payload, "receivable_id"))
    if not receivable_id:
        return {"ok": False, "error": "receivable_id required"}
    rec = db[COL_ACCOUNTING_RECEIVABLES].find_one({"receivable_id": receivable_id})
    if not rec:
        return {"ok": False, "error": f"receivable_not_found: {receivable_id}"}
    amount = _amount(_pull(payload, "amount")) or _amount(rec.get("amount"))
    prev_collected = _amount(rec.get("amount_collected"))
    total_collected = round(prev_collected + amount, 2)
    total_due = _amount(rec.get("amount"))
    status = "paid" if total_collected >= total_due else "partial"
    db[COL_ACCOUNTING_RECEIVABLES].update_one(
        {"receivable_id": receivable_id},
        {
            "$set": {
                "amount_collected": total_collected,
                "status": status,
                "collected_at": _norm(_pull(payload, "collected_at", default=now)),
                "updated_at": now,
            }
        },
    )
    payment_id = _new_id("collection")
    payment_doc = {
        "payment_id": payment_id,
        "receivable_id": receivable_id,
        "party_id": _norm(rec.get("party_id")),
        "entity_id": _norm(rec.get("entity_id")),
        "amount": amount,
        "currency": _norm(rec.get("currency") or "USD"),
        "method": _norm(_pull(payload, "method", default="transfer")),
        "direction": "inbound",
        "paid_at": _norm(_pull(payload, "collected_at", default=now)),
        "notes": _norm(_pull(payload, "notes")),
        "recorded_by": _norm(_pull(payload, "recorded_by", default="CHATGPT")),
        "source": _norm(_pull(payload, "source", default="chatgpt_mcp")),
        "created_at": now,
        "updated_at": now,
    }
    db[COL_ACCOUNTING_PAYMENTS].insert_one(payment_doc)
    saved = _serialize(db[COL_ACCOUNTING_RECEIVABLES].find_one({"receivable_id": receivable_id}))
    log_ops_action(
        actor="CHATGPT",
        action="record_collection",
        resource_type="collection",
        resource_id=payment_id,
        summary=f"Collection {amount} for {receivable_id}",
        tool_used="record_collection",
        metadata={"receivable_id": receivable_id, "status": status},
    )
    return {"ok": True, "payment_id": payment_id, "collection": _serialize(payment_doc), "receivable": saved}


def create_receivable_from_quote(quote_id: str, entity_id: str | None = None) -> dict[str, Any]:
    from raphiia_openai.operational.constants import COL_OPS_CLIENTS, COL_OPS_QUOTE_DRAFTS

    db = _db()
    quote = db[COL_OPS_QUOTE_DRAFTS].find_one({"quote_id": quote_id})
    if not quote:
        return {"ok": False, "error": f"quote_not_found: {quote_id}"}
    client_id = _norm(quote.get("client_id"))
    if not client_id:
        return {
            "ok": False,
            "error": "quote_missing_client",
            "detail": "La cotización no tiene client_id; no se puede crear AR sin identidad de cliente.",
            "quote_id": quote_id,
        }
    client = db[COL_OPS_CLIENTS].find_one({"$or": [{"client_id": client_id}, {"draft_id": client_id}]})
    if not client:
        return {
            "ok": False,
            "error": "client_not_found",
            "detail": f"client_id {client_id} no existe en ops_clients; evita contaminación de identidad.",
            "quote_id": quote_id,
            "client_id": client_id,
        }
    client_name = _norm(client.get("display_name") or client.get("legal_name") or client.get("trade_name"))
    if not client_name:
        return {
            "ok": False,
            "error": "client_name_missing",
            "detail": "Cliente sin display_name/legal_name; no usar title de cotización como nombre.",
            "quote_id": quote_id,
            "client_id": client_id,
        }
    amount = _amount(quote.get("total"))
    if amount <= 0:
        return {
            "ok": False,
            "error": "invalid_amount",
            "detail": "total de cotización debe ser > 0 para crear receivable",
            "quote_id": quote_id,
            "total": amount,
        }
    payload = {
        "client_name": client_name,
        "party_id": _norm(client.get("party_id")),
        "tax_id": _norm(client.get("tax_id")),
        "amount": amount,
        "due_date": "",
        "quote_id": quote_id,
        "entity_id": entity_id or _norm(quote.get("entity_id")) or "ent_pcdoctor",
        "notes": f"AR from quote {quote_id}",
        "source": "quote_link",
    }
    return create_receivable_draft(payload)


def create_payable_from_whatsapp(message: str, entity_id: str = "ent_pcdoctor", **extra: Any) -> dict[str, Any]:
    """Parse mensaje WhatsApp tipo 'cheque: proveedor 1500 vence 2026-07-20'."""
    text = _norm(message)
    body = text.split(":", 1)[1].strip() if ":" in text else text
    amount_match = re.search(r"(\d+(?:[.,]\d{1,2})?)", body)
    date_match = re.search(r"(20\d{2}-\d{2}-\d{2})", body)
    amount = _amount(amount_match.group(1).replace(",", ".")) if amount_match else 0.0
    due_date = date_match.group(1) if date_match else ""
    supplier_name = re.sub(r"\d+(?:[.,]\d{1,2})?", "", body)
    supplier_name = re.sub(r"20\d{2}-\d{2}-\d{2}", "", supplier_name).strip(" -,")
    blocked = {"ignore", "test", "cleanup-required", "do-not-use-parser", "n/a", "na", "xxx"}
    if supplier_name.lower() in blocked or len(supplier_name) < 2:
        return {
            "ok": False,
            "error": "invalid_supplier",
            "needs_review": True,
            "detail": "Proveedor inválido o de prueba; no se persiste payable.",
            "supplier_name": supplier_name,
        }
    if amount <= 0:
        return {
            "ok": False,
            "error": "invalid_amount",
            "needs_review": True,
            "detail": "Monto cero o ausente; no se persiste payable desde WhatsApp.",
            "parsed": {"supplier_name": supplier_name, "amount": amount, "due_date": due_date},
        }
    payload = {
        "supplier_name": supplier_name or extra.get("supplier_name", "Proveedor WhatsApp"),
        "amount": amount or extra.get("amount", 0),
        "due_date": due_date or extra.get("due_date", ""),
        "payable_type": "check",
        "entity_id": entity_id,
        "source": "whatsapp",
        "notes": text[:500],
        **{k: v for k, v in extra.items() if k not in {"supplier_name", "amount", "due_date"}},
    }
    return create_payable_draft(payload)


def list_payables(entity_id: str | None = None, status: str | None = None, limit: int = 50) -> dict[str, Any]:
    db = _db()
    query: dict[str, Any] = {"status": {"$ne": "promoted"}}
    if entity_id:
        query["entity_id"] = _norm(entity_id)
    if status:
        query["status"] = _norm(status)
    cursor = db[COL_ACCOUNTING_PAYABLES].find(query).sort("updated_at", -1).limit(max(1, min(limit, 100)))
    items = [_serialize(doc) for doc in cursor]
    return {"ok": True, "count": len(items), "payables": items}


try:
    _ensure_accounting_indexes()
except Exception:
    pass
