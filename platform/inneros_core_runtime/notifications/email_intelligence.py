"""Email Intelligence: documental classification and operational decision.

Local-first rules produce a stable contract for agents and small MCP clients.
This module does not send messages, create accounting entries, or call paid APIs.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

DOCUMENT_TYPES = {
    "spam_newsletter",
    "fyi",
    "factura",
    "nota_credito",
    "retencion",
    "estado_cuenta",
    "comprobante_pago",
    "cotizacion_propuesta",
    "lead_cliente",
    "soporte_incidente",
    "contrato_legal",
    "hackathon_funding_credits",
    "calendario_evento",
    "personal",
}

ROUTE_BY_DOCUMENT_TYPE: dict[str, dict[str, Any]] = {
    "factura": {"route_agent": "AG-17", "module": "contifico / facturacion SRI", "priority": "high", "requires_human_approval": True},
    "nota_credito": {"route_agent": "AG-17", "module": "contifico / notas credito", "priority": "high", "requires_human_approval": True},
    "retencion": {"route_agent": "AG-17", "module": "contifico / retenciones", "priority": "high", "requires_human_approval": True},
    "estado_cuenta": {"route_agent": "AG-08", "module": "finanzas / bancos", "priority": "high", "requires_human_approval": True},
    "comprobante_pago": {"route_agent": "AG-18", "module": "cobranzas / conciliacion", "priority": "high", "requires_human_approval": True},
    "cotizacion_propuesta": {"route_agent": "AG-38", "module": "quoteops / ventas", "priority": "normal", "requires_human_approval": False},
    "lead_cliente": {"route_agent": "AG-38", "module": "crm / lead", "priority": "normal", "requires_human_approval": False},
    "soporte_incidente": {"route_agent": "AG-31", "module": "ops / service guardian", "priority": "high", "requires_human_approval": False},
    "contrato_legal": {"route_agent": "AG-14", "module": "legal / contratos", "priority": "normal", "requires_human_approval": True},
    "hackathon_funding_credits": {"route_agent": "AG-54", "module": "funding / cloud credits / hackathons", "priority": "normal", "requires_human_approval": False},
    "calendario_evento": {"route_agent": "AG-53", "module": "calendar / admissions / events", "priority": "normal", "requires_human_approval": False},
    "personal": {"route_agent": "AG-05", "module": "correo / personal", "priority": "normal", "requires_human_approval": True},
    "delivery_failure": {"route_agent": "AG-05", "module": "correo / deliverability", "priority": "high", "requires_human_approval": False},
    "fyi": {"route_agent": "AG-05", "module": "correo / archivo", "priority": "low", "requires_human_approval": False},
    "spam_newsletter": {"route_agent": "AG-05", "module": "correo / archivo", "priority": "low", "requires_human_approval": False},
}

CATEGORY_FROM_DOCUMENT_TYPE = {
    "factura": "factura",
    "nota_credito": "sri_fiscal",
    "retencion": "sri_fiscal",
    "estado_cuenta": "extracto",
    "comprobante_pago": "pago",
    "cotizacion_propuesta": "cotizacion",
    "lead_cliente": "trusted_sender",
    "soporte_incidente": "incidente",
    "contrato_legal": "contrato",
    "hackathon_funding_credits": "trusted_sender",
    "calendario_evento": "trusted_sender",
    "personal": "general",
    "delivery_failure": "delivery_failure",
    "fyi": "marketing",
    "spam_newsletter": "marketing",
}

OWN_LEGAL_ENTITIES = (
    {"name": "PC Doctor", "patterns": ("pcdoctor", "pc doctor", "pcdoctor.ai", "pcdoctor.com.ec")},
    {"name": "InnerChispa", "patterns": ("innerchispa", "inner chispa", "innerchispa.us")},
    {"name": "InnerSpark", "patterns": ("innerspark", "inner spark", "innerspark.live")},
)

NEWSLETTER_MARKERS = (
    "newsletter", "unsubscribe", "darse de baja", "view in browser", "mailchimp", "smartbrief",
    "growth club", "growth rockstar", "mercury stories", "weekly digest", "boletin", "boletín",
)

FYI_MARKERS = ("para tu informacion", "para tu información", "fyi", "solo informativo", "novedades", "clipping")

PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("nota_credito", (r"\bnota\s+de\s+cr[eé]dito\b", r"\bcredit\s+note\b")),
    ("retencion", (r"\bretenci[oó]n\b", r"\bwithholding\b")),
    ("estado_cuenta", (r"\bestado\s+de\s+cuenta\b", r"\bextracto\s+bancario\b", r"\bbank\s+statement\b")),
    ("comprobante_pago", (r"\bcomprobante\s+de\s+pago\b", r"\bpayment\s+receipt\b", r"\bpago\s+recibido\b", r"\btransferencia\s+(?:recibida|realizada|exitosa)\b", r"\bconsumo\s+tarjeta\b", r"\bcargo\s+en\s+(?:su\s+)?tarjeta\b")),
    ("factura", (r"\bfactura(?:\s+electr[oó]nica)?\b", r"\binvoice\b", r"\bclave\s+de\s+acceso\b")),
    ("cotizacion_propuesta", (r"\bcotizaci[oó]n\b", r"\bproforma\b", r"\bproposal\b", r"\bquotation\b", r"\bpresupuesto\b")),
    ("soporte_incidente", (r"\bincidente\b", r"\breclamo\b", r"\boutage\b", r"\bdown\b", r"\bfalla\b", r"\bsoporte\b")),
    ("contrato_legal", (r"\bcontrato\b", r"\blegal\b", r"\bterms\b", r"\blicitaci[oó]n\b")),
    ("hackathon_funding_credits", (r"\bhackathon\b", r"\bdevpost\b", r"\bfunding\b", r"\bstartup\s+program\b", r"\bcloud\s+credits?\b", r"\bgoogle\s+cloud\b", r"\bdigitalocean\b", r"\baws\s+activate\b", r"\bazure\b")),
    ("calendario_evento", (r"\bentrevista\b", r"\binterview\b", r"\bcalendar\b", r"\bmeeting\b", r"\bagendar\b", r"\bwebinar\b")),
    ("lead_cliente", (r"\bquiero\s+(?:cotizar|comprar|contratar)\b", r"\bnecesito\s+(?:soporte|servicio|propuesta)\b", r"\bnew\s+lead\b")),
    ("delivery_failure", (r"\bmail\s+delivery\s+failed\b", r"\bundeliver(?:ed|able)\b", r"\breturned\s+message\b")),
)

FIELD_PATTERNS = {
    "ruc_candidates": re.compile(r"\b(\d{10}001|\d{13})\b"),
    "invoice_number": re.compile(r"(?:factura|invoice|comprobante)\s*(?:n[o°.]?\s*)?[:\s#-]*([A-Z0-9\-]{3,30})", re.I),
    "total": re.compile(r"(?:total|valor|amount|importe|monto)[:\s]*(?:USD|US\$|\$)?\s*([\d.,]+)", re.I),
    "date": re.compile(r"\b(20\d{2}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]20\d{2})\b"),
    "access_key": re.compile(r"\b(\d{49})\b"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(doc: dict[str, Any]) -> str:
    parts = [
        str(doc.get("subject") or ""),
        str(doc.get("body_text") or ""),
        str(doc.get("snippet") or ""),
        str(doc.get("body_preview") or ""),
        str(doc.get("from_addr") or doc.get("from") or doc.get("sender") or ""),
    ]
    for att in doc.get("attachments") or []:
        if isinstance(att, dict):
            parts.append(str(att.get("filename") or att.get("name") or ""))
    return "\n".join(parts).lower()


def _attachment_evidence(doc: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, att in enumerate(doc.get("attachments") or []):
        if not isinstance(att, dict):
            continue
        filename = str(att.get("filename") or att.get("name") or f"attachment_{idx}")[:160]
        raw = f"{doc.get('mail_id','')}|{filename}|{att.get('size','')}|{idx}"
        out.append({
            "filename": filename,
            "content_type": str(att.get("content_type") or att.get("mime") or "")[:100],
            "size": att.get("size"),
            "sha256_hint": hashlib.sha256(raw.encode()).hexdigest()[:16],
            "provenance": "email_attachment_metadata",
        })
    return out


def _find_document_type(blob: str) -> tuple[str, list[str]]:
    newsletter_hits = [m for m in NEWSLETTER_MARKERS if m in blob]
    has_financial = bool(re.search(r"\b(factura|invoice|retenci[oó]n|estado de cuenta|payment receipt|comprobante de pago|clave de acceso)\b", blob, re.I))
    if newsletter_hits and not has_financial:
        return "spam_newsletter", newsletter_hits[:4]
    for doc_type, patterns in PATTERNS:
        hits = [pat for pat in patterns if re.search(pat, blob, re.I)]
        if hits:
            return doc_type, hits[:4]
    if any(m in blob for m in FYI_MARKERS):
        return "fyi", [m for m in FYI_MARKERS if m in blob][:4]
    return "fyi", ["no_operational_signal"]


def _extract_fields(blob: str) -> dict[str, Any]:
    totals: list[float] = []
    for match in FIELD_PATTERNS["total"].finditer(blob):
        raw = match.group(1).replace(",", "")
        try:
            totals.append(float(raw))
        except ValueError:
            continue
    invoice = FIELD_PATTERNS["invoice_number"].search(blob)
    return {
        "ruc_candidates": list(dict.fromkeys(FIELD_PATTERNS["ruc_candidates"].findall(blob)))[:8],
        "invoice_number": invoice.group(1) if invoice else None,
        "total_candidates": totals[:5],
        "date_candidates": list(dict.fromkeys(FIELD_PATTERNS["date"].findall(blob)))[:5],
        "sri_access_keys": list(dict.fromkeys(FIELD_PATTERNS["access_key"].findall(blob)))[:3],
    }


def _resolve_legal_entity(blob: str, fields: dict[str, Any]) -> dict[str, Any]:
    evidence: list[str] = []
    entity = None
    for item in OWN_LEGAL_ENTITIES:
        hits = [p for p in item["patterns"] if p in blob]
        if hits:
            entity = item["name"]
            evidence.extend(hits[:3])
            break
    mismatch = False
    if re.search(r"\blupa\b|lupa\.com|lupa\s+corp", blob, re.I) and entity is None:
        entity = "external_or_ex_client"
        evidence.append("lupa_marker")
        mismatch = True
    if not entity and fields.get("ruc_candidates"):
        entity = "unresolved_ruc_present"
        evidence.extend(fields["ruc_candidates"][:2])
    return {"name": entity, "evidence": evidence, "mismatch": mismatch, "source": "document_text_not_mailbox"}


def decide_email(doc: dict[str, Any], base_analysis: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the required durable decision contract for one email."""
    blob = _text(doc)
    document_type, matched = _find_document_type(blob)
    fields = _extract_fields(blob)
    legal_entity = _resolve_legal_entity(blob, fields)
    route = dict(ROUTE_BY_DOCUMENT_TYPE.get(document_type) or ROUTE_BY_DOCUMENT_TYPE["fyi"])

    confidence = 0.9 if document_type not in {"fyi", "spam_newsletter"} else 0.82
    if document_type in {"factura", "nota_credito", "retencion", "estado_cuenta", "comprobante_pago"} and not (
        fields.get("ruc_candidates") or fields.get("invoice_number") or fields.get("total_candidates") or fields.get("sri_access_keys") or doc.get("has_attachment") or doc.get("attachments")
    ):
        confidence = 0.62
        route["requires_human_approval"] = True
    if legal_entity.get("mismatch"):
        route["requires_human_approval"] = True
        route["priority"] = "normal"

    no_auto_task = document_type in {"spam_newsletter", "fyi"}
    suggested_actions = _suggested_actions(document_type, legal_entity, fields, no_auto_task)
    rationale = _rationale(document_type, matched, legal_entity, no_auto_task)

    return {
        "ok": True,
        "mail_id": str(doc.get("mail_id") or ""),
        "document_type": document_type,
        "category": CATEGORY_FROM_DOCUMENT_TYPE.get(document_type, "general"),
        "confidence": round(confidence, 2),
        "priority": "low" if no_auto_task else route.get("priority", "normal"),
        "rationale": rationale,
        "matched_signals": matched,
        "legal_entity": legal_entity,
        "counterparty": {"from_addr": doc.get("from_addr") or doc.get("from"), "source": "sender_header"},
        "extracted_fields": fields,
        "attachments": _attachment_evidence(doc),
        "suggested_actions": suggested_actions,
        "route_agent": route.get("route_agent"),
        "route_module": route.get("module"),
        "requires_human_approval": bool(route.get("requires_human_approval")),
        "create_ops_task": not no_auto_task,
        "whatsapp_policy": "digest_only" if no_auto_task else ("priority_only" if route.get("priority") == "high" else "no_immediate_alert"),
        "model_plan": {
            "triage": "intel:qwen2.5vl:7b when local model service is available; deterministic rules are fallback",
            "escalation": "amd:qwen3 for ambiguous or high-impact cases only",
        },
        "analysis_source": "email_intelligence_v1_local_rules",
        "decided_at": _now(),
    }


def _suggested_actions(document_type: str, legal_entity: dict[str, Any], fields: dict[str, Any], no_auto_task: bool) -> list[str]:
    if no_auto_task:
        return ["Archivar o dejar para digest", "No crear ops_task ni WhatsApp inmediato"]
    if document_type == "delivery_failure":
        return ["Verificar dirección del destinatario", "Reenviar correo corregido si aplica"]
    if document_type == "factura":
        actions = ["Validar emisor, receptor legal, numero, fecha, total y moneda", "Conservar provenance mail_id + hash de adjuntos"]
        if legal_entity.get("mismatch") or not legal_entity.get("name"):
            actions.append("Bloquear registro contable automatico hasta resolver receptor legal")
        else:
            actions.append("Preparar borrador financiero gated para revision humana")
        return actions
    if document_type in {"retencion", "nota_credito"}:
        return ["Extraer clave SRI/RUC/numero si existe", "Enviar a AG-17 con aprobacion humana"]
    if document_type == "estado_cuenta":
        return ["Extraer entidad/cuenta/periodo/saldo", "Enviar a AG-08 para conciliacion"]
    if document_type == "hackathon_funding_credits":
        return ["Evaluar beneficio real, deadline y requisitos", "Crear oportunidad concreta sin accion inventada"]
    if document_type == "calendario_evento":
        return ["Revisar fecha/deadline y proponer agenda", "Pedir aprobacion si implica responder o inscribirse"]
    return ["Revisar evidencia extraida", "Enrutar al agente sugerido"]


def _rationale(document_type: str, matched: list[str], legal_entity: dict[str, Any], no_auto_task: bool) -> str:
    bits = [f"document_type={document_type}"]
    if matched:
        bits.append("signals=" + ",".join(matched[:4]))
    if no_auto_task:
        bits.append("no_ops_task_for_newsletter_or_fyi")
    if legal_entity.get("name"):
        bits.append(f"legal_entity={legal_entity['name']}")
    if legal_entity.get("mismatch"):
        bits.append("legal_entity_mismatch_gate")
    return "; ".join(bits)


def before_after_matrix(fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for doc in fixtures:
        decision = decide_email(doc)
        rows.append({
            "mail_id": doc.get("mail_id"),
            "subject": str(doc.get("subject") or "")[:120],
            "document_type": decision["document_type"],
            "priority": decision["priority"],
            "create_ops_task": decision["create_ops_task"],
            "route_agent": decision["route_agent"],
            "requires_human_approval": decision["requires_human_approval"],
            "rationale": decision["rationale"],
        })
    return {"ok": True, "count": len(rows), "rows": rows}
