"""Clasificador unificado de correo — RalfIA + Swarm (reglas compartidas).

Prioridad: trusted domain → junk fuerte → categorías de negocio → marketing → general.
"""

from __future__ import annotations

import re
from typing import Any

# Dominios / remitentes de confianza — bancos EC, SRI, fisco, pagos, servicios críticos
TRUSTED_DOMAIN_FRAGMENTS = (
    "sri.gob.ec",
    "sri.gov.ec",
    "servicio.net",
    "irs.gov",
    "internalrevenue",
    "pichincha.com",
    "produbanco.com",
    "bancoguayaquil.com",
    "bancointernacional.com",
    "bolivariano.com",
    "banco.pacifico",
    "pacifico.fin.ec",
    "jep.coop",
    "visionfund",
    "cooprogreso",
    "facilito.com.ec",
    "deuna.com",
    "payphone",
    "paypal.com",
    "mercadopago",
    "stripe.com",
    "bce.fin.ec",
    "contifico.com",
    "netlife.info.ec",
    "prime-host",
    "primehosting",
    "pcdoctor.com.ec",
    "innerchispa",
    "speechmatics.com",
)

# Palabras de negocio — alta prioridad (frases o términos específicos)
HIGH_PRIORITY_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(?:factura|invoice|comprobante)\b", "factura"),
    (r"\b(?:transferencia|wire transfer|swift|dep[oó]sito|deposit received|abono)\b", "transferencia"),
    (r"\b(?:estado de cuenta|extracto bancario|bank statement)\b", "extracto"),
    (r"\b(?:pago recibido|payment received|cobro|saldo pendiente|vencid[oa]|mora)\b", "pago"),
    (r"\b(?:retenci[oó]n|ruc\b|autorizaci[oó]n sri|nota de cr[eé]dito)\b", "sri_fiscal"),
    (r"\b(?:reclamo|complaint|incidente|falla|servidor ca[ií]do|down\b|outage)\b", "incidente"),
    (r"\b(?:cotizaci[oó]n|proforma|presupuesto|purchase order|orden de compra)\b", "cotizacion"),
    (r"\b(?:contrato|licitaci[oó]n|despacho aduanero|aduana)\b", "contrato"),
    (r"\b(?:mail delivery failed|undeliver(?:ed|able)|returned message)\b", "delivery_failure"),
    (r"\b(?:irs\b|internal revenue|tax notice|impuesto)\b", "fiscal_us"),
    (r"\b(?:vencimiento|aviso de vencimiento|suspensi[oó]n|hosting)\b", "servicio_vencimiento"),
)

# Promos bancarias — remitente confiable pero no transaccional
BANK_MARKETING_PATTERNS = (
    r"\bdisfruta\b",
    r"\bbeneficios exclusivos\b",
    r"\bcombos?\b",
    r"\bpromoci[oó]n\b",
    r"\bjueves con\b",
    r"\brecibe \$\d",
    r"\bred crab\b",
    r"\bruta de haciendas\b",
    r"\btransforma tu presupuesto\b",
    r"\bcapacitaci[oó]n\b",
    r"\bhas invited you to\b",
    r"\binvitation to join\b",
)

# Señales transaccionales bancarias — sí alertar
TRANSACTIONAL_BANK_PATTERNS = (
    r"\bconsumo tarjeta\b",
    r"\bcargo en (?:su )?tarjeta\b",
    r"\b(?:d[eé]bito|cr[eé]dito) por usd\b",
    r"\bestado de cuenta\b",
    r"\bextracto bancario\b",
    r"\btransferencia (?:recibida|realizada|enviada|exitosa)\b",
    r"\bcomprobante de (?:pago|transferencia)\b",
    r"\bsaldo (?:disponible|insuficiente)\b",
)

# Marketing / ruido — baja prioridad si no hay señal de negocio fuerte
MARKETING_PATTERNS = (
    r"\bnewsletter\b",
    r"\bunsubscribe\b",
    r"\bdarse de baja\b",
    r"\bdescuento exclusivo\b",
    r"\boferta limitada\b",
    r"\btienda en l[ií]nea\b",
    r"\bpromoci[oó]n\b",
    r"\bpeople you may know\b",
    r"\binvitaci[oó]n a conectar\b",
    r"\bhas ganado un premio sorpresa\b",
    r"\bcrypto airdrop\b",
    r"\bmailchimp\b",
    r"\bsmartbrief\b",
    r"\bcta smartbrief\b",
)

SOCIAL_JUNK_DOMAINS = (
    "linkedin.com",
    "facebookmail",
    "twitter.com",
    "instagram.com",
    "calendar-notification",
)

JUNK_STRONG = (
    "unsubscribe",
    "darse de baja",
    "mailchimp",
    "lotería",
    "loteria",
    "casino",
)


def _blob(subject: str, body: str, from_addr: str) -> str:
    return f"{subject} {body} {from_addr}".lower()


def _trusted_domain(blob: str, extra_domains: list[str] | None = None) -> str | None:
    for dom in TRUSTED_DOMAIN_FRAGMENTS:
        if dom in blob:
            return dom
    for dom in extra_domains or []:
        d = dom.lower().strip()
        if d and d in blob:
            return d
    return None


def _is_junk(blob: str, from_addr: str, *, has_business_signal: bool) -> tuple[bool, str]:
    if has_business_signal:
        return False, ""
    for marker in JUNK_STRONG:
        if marker in blob:
            return True, marker
    marketing_hits = sum(1 for p in MARKETING_PATTERNS if re.search(p, blob, re.I))
    if marketing_hits >= 2:
        return True, "marketing_multiple"
    for social in SOCIAL_JUNK_DOMAINS:
        if social in blob:
            return True, social
    if re.search(r"\bnoreply\b|\bno-reply\b", from_addr, re.I):
        if marketing_hits >= 1 and not re.search(
            r"sri|banco|factura|pago|transfer|deposit|irs|vencim", blob, re.I
        ):
            return True, "noreply_marketing"
    return False, ""


def classify_email(
    doc: dict[str, Any],
    *,
    extra_keywords: list[str] | None = None,
    extra_domains: list[str] | None = None,
) -> dict[str, Any]:
    """Clasificación v3 — categoría, prioridad, si alertar WhatsApp."""
    subject = str(doc.get("subject") or "(sin asunto)")[:240]
    body = str(doc.get("body_text") or doc.get("snippet") or doc.get("body_preview") or "")
    from_addr = str(doc.get("from_addr") or doc.get("from") or doc.get("sender") or "")
    blob = _blob(subject, body, from_addr)

    matched_high: list[str] = []
    category = "general"
    for pattern, label in HIGH_PRIORITY_PATTERNS:
        if re.search(pattern, blob, re.I):
            matched_high.append(label)
            category = label

    for kw in extra_keywords or []:
        token = kw.lower().strip()
        if len(token) >= 5 and re.search(rf"\b{re.escape(token)}\b", blob, re.I):
            matched_high.append(f"kw:{token}")
            if category == "general":
                category = "keyword_match"

    trusted = _trusted_domain(blob, extra_domains)
    transactional_bank = any(re.search(p, blob, re.I) for p in TRANSACTIONAL_BANK_PATTERNS)
    bank_marketing = any(re.search(p, blob, re.I) for p in BANK_MARKETING_PATTERNS)

    if trusted and category in ("general", "keyword_match"):
        category = "trusted_sender"

    # Solo categorías de negocio concretas — no basta ser remitente confiable
    strong_labels = {
        "factura", "pago", "transferencia", "extracto", "sri_fiscal", "fiscal_us",
        "incidente", "contrato", "delivery_failure", "servicio_vencimiento",
    }
    has_strong = any(m in strong_labels for m in matched_high)
    if transactional_bank:
        has_strong = True
        category = "transferencia" if category in ("general", "trusted_sender", "keyword_match") else category
        matched_high.append("transactional_bank")
    elif category == "cotizacion" and bank_marketing:
        matched_high = [m for m in matched_high if m != "cotizacion"]
        category = "marketing"
        has_strong = False
    elif category == "servicio_vencimiento" and re.search(r"\bpromoci[oó]n\b", blob, re.I):
        if not re.search(r"\b(?:vencim|suspensi[oó]n|renovaci[oó]n|caduc)\b", blob, re.I):
            matched_high = [m for m in matched_high if m != "servicio_vencimiento"]
            category = "marketing"
            has_strong = False
    has_business = has_strong

    if trusted and bank_marketing and not transactional_bank and not has_strong:
        return {
            "category": "marketing",
            "priority": "low",
            "alert": False,
            "reason": f"bank_promo ({trusted})",
            "matched": matched_high,
            "trusted_domain": trusted,
            "analysis_source": "email_classifier_v3",
        }

    junk, junk_reason = _is_junk(blob, from_addr, has_business_signal=has_business)
    if junk:
        return {
            "category": "marketing",
            "priority": "low",
            "alert": False,
            "reason": f"junk ({junk_reason})",
            "matched": matched_high,
            "analysis_source": "email_classifier_v3",
        }

    if re.search(r"\b(?:confirmation|verification|c[oó]digo|otp|one.time password)\b", blob, re.I):
        return {
            "category": "security_code",
            "priority": "normal",
            "alert": False,
            "reason": "codigo_verificacion",
            "matched": matched_high,
            "analysis_source": "email_classifier_v3",
        }

    if matched_high:
        if has_strong:
            priority = "high"
            alert = True
        elif category in ("keyword_match", "trusted_sender"):
            priority = "normal"
            alert = False
        else:
            priority = "normal"
            alert = False
        return {
            "category": category,
            "priority": priority,
            "alert": alert,
            "reason": "; ".join(matched_high[:4]),
            "matched": matched_high,
            "trusted_domain": trusted,
            "analysis_source": "email_classifier_v3",
        }

    if any(re.search(p, blob, re.I) for p in MARKETING_PATTERNS):
        return {
            "category": "marketing",
            "priority": "low",
            "alert": False,
            "reason": "marketing_weak",
            "matched": [],
            "analysis_source": "email_classifier_v3",
        }

    if trusted:
        return {
            "category": "trusted_sender",
            "priority": "normal",
            "alert": False,
            "reason": f"trusted_no_keyword ({trusted})",
            "matched": [],
            "trusted_domain": trusted,
            "analysis_source": "email_classifier_v3",
        }

    return {
        "category": "general",
        "priority": "normal",
        "alert": False,
        "reason": "sin_señal_fuerte",
        "matched": [],
        "analysis_source": "email_classifier_v3",
    }


def swarm_importance_from_classification(cl: dict[str, Any]) -> str:
    """Mapeo a importancia Swarm: alta | normal | baja."""
    if cl.get("priority") == "low":
        return "baja"
    if cl.get("priority") == "high" and cl.get("alert"):
        return "alta"
    if cl.get("priority") == "high":
        return "alta"
    return "normal"
