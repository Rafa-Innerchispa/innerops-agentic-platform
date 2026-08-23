"""
Gates operativos OS Central — Playbook V2 + SOPs Master.

Bloqueos de calidad antes de crear registros o enviar entregables.
"""

from __future__ import annotations

import re
from typing import Any

from tools.mongo import get_db

PLACEHOLDER_PATTERNS = [
    r"@today",
    r"\bpendiente\b",
    r"\bpor definir\b",
    r"\bN/A\b",
    r"\bTBD\b",
    r"\bxxx\b",
    r"\.\.\.",
]

BLOCKING = "bloqueante"
HIGH = "alta"
MEDIUM = "media"
LOW = "baja"


def _result(gate: str, passed: bool, severity: str, message: str, **extra) -> dict:
    return {"gate": gate, "passed": passed, "severity": severity, "message": message, **extra}


def check_duplicate_client(ruc: str | None = None, name: str | None = None, phone: str | None = None, email: str | None = None) -> dict:
    """Gate anti-duplicación DB04."""
    db = get_db()
    queries = []
    if ruc:
        queries.append({"ruc": ruc})
    if name:
        queries.append({"name": {"$regex": f"^{re.escape(name.strip())}$", "$options": "i"}})
    if phone:
        queries.append({"phone": phone})
    if email:
        queries.append({"email": email})
    if not queries:
        return _result("anti_duplicacion_cliente", True, LOW, "Sin criterios de búsqueda")
    for q in queries:
        hit = db.clients.find_one(q, {"_id": 0, "client_id": 1, "name": 1, "ruc": 1})
        if hit:
            return _result(
                "anti_duplicacion_cliente",
                False,
                BLOCKING,
                f"Posible duplicado: {hit.get('name')} ({hit.get('ruc', '')})",
                existing_client_id=hit.get("client_id"),
            )
    return _result("anti_duplicacion_cliente", True, LOW, "Sin duplicados detectados")


def check_hub_first(client_id: str | None) -> dict:
    """Gate Hub-first: cliente debe tener hub."""
    if not client_id:
        return _result("hub_first", False, BLOCKING, "Falta client_id")
    db = get_db()
    client = db.clients.find_one({"client_id": client_id}, {"_id": 0, "hub_id": 1, "hub_ready": 1})
    if not client:
        return _result("hub_first", False, BLOCKING, "Cliente no existe")
    if not client.get("hub_ready") or not client.get("hub_id"):
        return _result("hub_first", False, BLOCKING, "Cliente sin Hub — crear hub antes de documentos")
    hub = db.client_hubs.find_one({"hub_id": client["hub_id"]}, {"_id": 0})
    if not hub:
        return _result("hub_first", False, BLOCKING, "hub_id registrado pero hub no existe")
    return _result("hub_first", True, LOW, "Hub OK", hub_id=client["hub_id"])


def check_placeholders(text: str, field: str = "texto") -> dict:
    """Gate anti-placeholders."""
    if not text:
        return _result("anti_placeholders", True, LOW, f"{field} vacío (no bloquea por placeholder)")
    for pat in PLACEHOLDER_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return _result("anti_placeholders", False, BLOCKING, f"Placeholder detectado en {field}: {pat}")
    return _result("anti_placeholders", True, LOW, "Sin placeholders")


def calc_quote_from_lines(quote_id: str) -> dict:
    """DB38 manda — recalcula desde líneas."""
    db = get_db()
    quote = db.quotes.find_one({"quote_id": quote_id}, {"_id": 0})
    if not quote:
        # Legacy: buscar por inspection_id en quote_headers
        quote = db.quote_headers.find_one({"inspection_id": quote_id}, {"_id": 0})
        if quote:
            lines = list(db.quote_lines.find({"inspection_id": quote_id}, {"_id": 0}))
        else:
            return {"subtotal": 0, "iva": 0, "total": 0, "lines": []}
    else:
        lines = list(db.quote_lines.find({"quote_id": quote_id}, {"_id": 0}))

    subtotal = 0.0
    for line in lines:
        qty = float(line.get("cantidad") or line.get("qty") or 1)
        price = float(line.get("precio_unitario") or line.get("unit_price") or 0)
        line_sub = float(line.get("subtotal_linea") or line.get("subtotal") or qty * price)
        subtotal += line_sub

    apply_iva = quote.get("iva_15", True)
    if quote.get("iva_15") is False:
        apply_iva = False
    monto_iva = round(subtotal * 0.15, 2) if apply_iva else 0.0
    total = subtotal + monto_iva
    return {"subtotal": round(subtotal, 2), "iva": round(monto_iva, 2), "total": round(total, 2), "lines": lines}


def check_db38_math(quote_id: str, tolerance: float = 0.02) -> dict:
    """Gate matemático: cabecera debe coincidir con suma DB38."""
    db = get_db()
    calc = calc_quote_from_lines(quote_id)
    if not calc["lines"]:
        return _result("db38_matematica", False, BLOCKING, "Cotización sin líneas DB38")

    quote = db.quotes.find_one({"quote_id": quote_id}, {"_id": 0}) or db.quote_headers.find_one(
        {"inspection_id": quote_id}, {"_id": 0}
    )
    if not quote:
        return _result("db38_matematica", False, BLOCKING, "Cotización no encontrada")

    header_total = float(quote.get("total") or 0)
    header_sub = float(quote.get("subtotal") or 0)
    calc_total = calc["total"]
    calc_sub = calc["subtotal"]

    if abs(header_total - calc_total) > tolerance or abs(header_sub - calc_sub) > tolerance:
        return _result(
            "db38_matematica",
            False,
            BLOCKING,
            f"Descuadre: cabecera total={header_total} vs DB38={calc_total}",
            calculated=calc,
            header={"subtotal": header_sub, "total": header_total},
        )
    return _result("db38_matematica", True, LOW, "Matemática DB38 OK", calculated=calc)


def check_pdf_first(quote_id: str | None = None, report_id: str | None = None, client_id: str | None = None) -> dict:
    """Gate PDF-first: debe existir documento exportable."""
    db = get_db()
    query: dict[str, Any] = {}
    if quote_id:
        query = {"target_type": "quote", "target_id": quote_id}
    elif report_id:
        query = {"target_type": "technical_report", "target_id": report_id}
    elif client_id:
        query = {"client_id": client_id}
    else:
        return _result("pdf_first", False, BLOCKING, "Falta quote_id, report_id o client_id")

    doc = db.documents.find_one(query, {"_id": 0})
    if not doc:
        # Fallback legacy: export en data/exports sin colección documents
        return _result("pdf_first", False, BLOCKING, "No existe documento PDF-first en colección documents")
    ph = check_placeholders(doc.get("path", "") + " " + doc.get("notas", ""), "documento")
    if not ph["passed"]:
        return ph
    return _result("pdf_first", True, LOW, "PDF-first OK", document_id=doc.get("document_id"))


def check_financial_traceability(work_id: str) -> dict:
    """Gate dinero real: cobro → DB31."""
    db = get_db()
    work = db.works.find_one({"work_id": work_id}, {"_id": 0})
    if not work:
        return _result("dinero_real_db31", True, LOW, "Trabajo no existe — no aplica")
    cobrado = float(work.get("precio_cobrado") or 0)
    if cobrado <= 0:
        return _result("dinero_real_db31", True, LOW, "Sin cobro — DB31 no requerida")
    tx = db.transactions.find_one({"work_id": work_id}, {"_id": 0, "transaction_id": 1})
    if not tx:
        return _result("dinero_real_db31", False, BLOCKING, f"Cobro ${cobrado} sin transacción DB31")
    return _result("dinero_real_db31", True, LOW, "Transacción DB31 enlazada", transaction_id=tx.get("transaction_id"))


def run_ready_to_send(quote_id: str, client_id: str | None = None) -> dict:
    """
    Gate compuesto "Listo para enviar" — SOP Master A3.
    """
    results = [
        check_hub_first(client_id),
        check_db38_math(quote_id),
        check_pdf_first(quote_id=quote_id),
    ]
    db = get_db()
    quote = db.quotes.find_one({"quote_id": quote_id}, {"_id": 0, "scope": 1, "client_id": 1})
    if quote:
        cid = client_id or quote.get("client_id")
        if cid:
            results[0] = check_hub_first(cid)
        if quote.get("scope"):
            results.append(check_placeholders(quote["scope"], "alcance cotización"))

    blocking = [r for r in results if not r["passed"] and r["severity"] == BLOCKING]
    return {
        "ready": len(blocking) == 0,
        "quote_id": quote_id,
        "gates": results,
        "blocking_count": len(blocking),
    }


def run_verification_rules(target_type: str, target_id: str) -> list[dict]:
    """Evalúa reglas DB41 activas y guarda validation_results."""
    db = get_db()
    rules = list(db.verification_rules.find({"activa": True}, {"_id": 0}))
    results = []
    for rule in rules:
        passed = True
        msg = "OK"
        rid = rule.get("rule_id")
        if "DB38" in str(rule.get("aplica_a", [])):
            if target_type == "quote":
                g = check_db38_math(target_id)
                passed = g["passed"]
                msg = g["message"]
        if "PDF-first" in str(rule.get("aplica_a", [])) and target_type == "quote":
            g = check_pdf_first(quote_id=target_id)
            if not g["passed"]:
                passed = False
                msg = g["message"]
        entry = {
            "target_type": target_type,
            "target_id": target_id,
            "rule_id": rid,
            "passed": passed,
            "mensaje": msg,
        }
        db.validation_results.insert_one({**entry, "at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc)})
        results.append(entry)
    return results
