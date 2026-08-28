"""Ledger financiero personal y operativo de InnerOS.

Provee estructura canónica, catálogo de cuentas con resolución por alias,
registro de transacciones y consultas agregadas.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from bson import ObjectId

from raphiia_openai import mongo_store
from raphiia_openai.operational.audit import log_ops_action

COL_LEDGER_TRANSACTIONS = "ledger_transactions"

# Catálogo canónico de cuentas e instrumentos
ACCOUNT_CATALOG = {
    "pacifico_personal": {
        "id": "pacifico_personal",
        "name": "Cuenta Personal Banco del Pacífico",
        "bank": "Banco del Pacífico",
        "type": "bank_account",
        "scope": "personal",
        "aliases": [
            "mi cuenta personal del pacífico",
            "cuenta del pacifico",
            "pacifico personal",
            "cuenta personal pacifico",
        ]
    },
    "visa_corporativa_3606": {
        "id": "visa_corporativa_3606",
        "name": "Visa Corporativa (*3606)",
        "bank": "Banco del Pacífico",
        "type": "credit_card",
        "scope": "corporate",
        "aliases": [
            "visa corporativa",
            "tarjeta corporativa",
            "visa 3606",
            "tarjeta visa corporativa terminada en 3606",
            "visa corporativa terminada 3606"
        ]
    }
}

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _db():
    return mongo_store.get_db()

def _norm(value: Any) -> str:
    return str(value or "").strip()

def _amount(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0

def resolve_account_alias(alias: str) -> dict[str, Any] | None:
    """Resuelve un alias natural a un instrumento del catálogo canónico."""
    raw = _norm(alias).lower()
    if not raw:
        return None
        
    # Búsqueda exacta en IDs
    if raw in ACCOUNT_CATALOG:
        return ACCOUNT_CATALOG[raw]
        
    # Búsqueda fuzzy en aliases
    best_match = None
    best_score = 0
    raw_tokens = set(re.findall(r'\w+', raw))
    
    for acc_id, acc_data in ACCOUNT_CATALOG.items():
        for a in acc_data["aliases"]:
            a_lower = a.lower()
            if raw in a_lower or a_lower in raw:
                return acc_data
            
            # Token overlap
            a_tokens = set(re.findall(r'\w+', a_lower))
            if a_tokens and raw_tokens:
                overlap = len(a_tokens & raw_tokens)
                score = overlap / max(len(a_tokens), len(raw_tokens))
                if score > best_score and score > 0.5:
                    best_score = score
                    best_match = acc_data
                    
    return best_match


def record_transaction(payload: dict[str, Any]) -> dict[str, Any]:
    """Registra un movimiento en el ledger estructurado."""
    db = _db()
    
    transaction_id = _norm(payload.get("transaction_id")) or f"tx_{ObjectId()}"
    account_input = _norm(payload.get("source_account") or payload.get("payment_instrument"))
    resolved_acc = resolve_account_alias(account_input) if account_input else None
    
    source_account_id = resolved_acc["id"] if resolved_acc else account_input
    scope = resolved_acc["scope"] if resolved_acc else _norm(payload.get("scope", "personal"))
    
    doc = {
        "transaction_id": transaction_id,
        "datetime": _norm(payload.get("datetime")) or _now_iso(),
        "amount": _amount(payload.get("amount")),
        "currency": _norm(payload.get("currency", "USD")),
        "direction": _norm(payload.get("direction", "outbound")),
        "category": _norm(payload.get("category")),
        "subcategory": _norm(payload.get("subcategory")),
        "concept": _norm(payload.get("concept")),
        "counterparty": _norm(payload.get("counterparty") or payload.get("entity_id")),
        "payment_method": _norm(payload.get("payment_method", "bank_transfer")),
        "source_account": source_account_id,
        "scope": scope,
        
        # Seguros y salud
        "insurance_coverage": payload.get("insurance_coverage", False),
        "covered_amount": _amount(payload.get("covered_amount")),
        "out_of_pocket_amount": _amount(payload.get("out_of_pocket_amount")),
        
        # Metadata / Enlaces
        "reference": _norm(payload.get("reference")),
        "evidence": _norm(payload.get("evidence")),
        "linked_event": _norm(payload.get("linked_event") or payload.get("linked_health_event")),
        
        "created_at": _now_iso(),
        "updated_at": _now_iso()
    }
    
    db[COL_LEDGER_TRANSACTIONS].update_one(
        {"transaction_id": transaction_id},
        {"$set": doc},
        upsert=True
    )
    
    log_ops_action(
        actor="CHATGPT",
        action="record_ledger_transaction",
        resource_type="ledger_transaction",
        resource_id=transaction_id,
        summary=f"Ledger Tx {doc['amount']} {doc['currency']} a {doc['counterparty']}",
        tool_used="record_transaction",
        metadata={"amount": doc["amount"], "category": doc["category"]}
    )
    
    # Remover _id para serializar
    doc.pop("_id", None)
    return {"ok": True, "transaction_id": transaction_id, "transaction": doc, "resolved_account": resolved_acc}


def query_ledger(filters: dict[str, Any], limit: int = 100) -> dict[str, Any]:
    """Consulta agregable del ledger."""
    db = _db()
    
    query = {}
    if filters.get("category"):
        query["category"] = _norm(filters["category"])
    if filters.get("counterparty"):
        query["counterparty"] = {"$regex": re.escape(_norm(filters["counterparty"])), "$options": "i"}
    if filters.get("source_account"):
        resolved = resolve_account_alias(filters["source_account"])
        query["source_account"] = resolved["id"] if resolved else filters["source_account"]
    if filters.get("direction"):
        query["direction"] = _norm(filters["direction"])
    if filters.get("scope"):
        query["scope"] = _norm(filters["scope"])
        
    # Period matching
    if filters.get("start_date") or filters.get("end_date"):
        date_q = {}
        if filters.get("start_date"):
            date_q["$gte"] = _norm(filters["start_date"])
        if filters.get("end_date"):
            date_q["$lte"] = _norm(filters["end_date"])
        query["datetime"] = date_q

    cursor = db[COL_LEDGER_TRANSACTIONS].find(query).sort("datetime", -1).limit(limit)
    transactions = []
    for doc in cursor:
        doc["_id"] = str(doc["_id"])
        transactions.append(doc)
        
    # Simple aggregations
    total_outbound = sum(t["amount"] for t in transactions if t["direction"] == "outbound")
    total_inbound = sum(t["amount"] for t in transactions if t["direction"] == "inbound")
    total_out_of_pocket = sum(t.get("out_of_pocket_amount", 0) for t in transactions)
    
    # Aggregate by category
    by_category = {}
    for t in transactions:
        cat = t.get("category", "uncategorized")
        by_category[cat] = by_category.get(cat, 0) + (t["amount"] if t["direction"] == "outbound" else -t["amount"])
        
    return {
        "ok": True,
        "count": len(transactions),
        "transactions": transactions,
        "aggregations": {
            "total_outbound": round(total_outbound, 2),
            "total_inbound": round(total_inbound, 2),
            "total_out_of_pocket": round(total_out_of_pocket, 2),
            "net_spend_by_category": {k: round(v, 2) for k, v in by_category.items()}
        }
    }


def migrate_initial_data() -> dict[str, Any]:
    """Migra los movimientos solicitados explícitamente en el checklist para arrancar el ledger."""
    transactions = [
        {
            "transaction_id": "tx_mediglobal_terapia_usd2",
            "datetime": "2026-08-20T10:00:00Z",
            "amount": 2.28,
            "currency": "USD",
            "direction": "outbound",
            "category": "health",
            "subcategory": "physical_therapy",
            "concept": "Terapia física Mediglobal",
            "counterparty": "Mediglobal",
            "payment_method": "bank_transfer",
            "source_account": "pacifico_personal",
            "scope": "personal",
            "insurance_coverage": True,
            "out_of_pocket_amount": 2.28
        },
        {
            "transaction_id": "tx_sueldo_hector_usd30",
            "datetime": "2026-08-20T11:00:00Z",
            "amount": 30.00,
            "currency": "USD",
            "direction": "outbound",
            "category": "payroll",
            "subcategory": "salary_balance",
            "concept": "Saldo de sueldo",
            "counterparty": "Héctor José Mejías Rosales",
            "payment_method": "bank_transfer",
            "source_account": "pacifico_personal",
            "scope": "corporate"
        },
        {
            "transaction_id": "tx_mediglobal_rx_usd13",
            "datetime": "2026-08-20T12:00:00Z",
            "amount": 13.60,
            "currency": "USD",
            "direction": "outbound",
            "category": "health",
            "subcategory": "xrays",
            "concept": "Radiografías cervicales Mediglobal",
            "counterparty": "Mediglobal",
            "payment_method": "credit_card",
            "source_account": "visa_corporativa_3606",
            "scope": "corporate",
            "insurance_coverage": True,
            "out_of_pocket_amount": 13.60
        }
    ]
    
    results = []
    for tx in transactions:
        results.append(record_transaction(tx))
        
    return {"ok": True, "migrated": len(results), "details": results}
