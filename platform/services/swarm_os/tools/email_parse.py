"""Parse incoming mail for guided demo — RUC, quote intent, client hints."""

from __future__ import annotations

import re
from typing import Any

# Remitentes automáticos / fiscales que NO son solicitudes de cotización
AUTOMATED_SENDER_PATTERNS: tuple[str, ...] = (
    "infosri",
    "info@sri",
    "sri.gob",
    "sercop",
    "noreply",
    "no-reply",
    "donotreply",
    "do-not-reply",
    "comprobantes@",
    "comprobante@",
    "facturacion@",
    "factura@",
    "notificaciones@",
    "notification@",
    "mailer-daemon",
    "postmaster@",
    "bounce@",
    "alertas@",
    "sistema@",
    "robot@",
    "automated@",
    "newsletter",
    "marketing@",
    "promo@",
    "bmsend.com",
    "mailchimp",
    "sendgrid",
    "info.grabaseg",
)

QUOTE_KEYWORDS: tuple[str, ...] = (
    "cotiz",
    "quote",
    "presupuesto",
    "proforma",
    "switch",
    "poe",
    "cámara",
    "camara",
    "cctv",
    "instal",
    "urgent",
    "urgente",
    "solicit",
    "request",
    "precio",
    "monto",
    "propuesta",
    "necesit",
    "requer",
)


def extract_ruc_from_text(text: str) -> str | None:
    if not text:
        return None
    lower = text.lower()
    m = re.search(r"\b(\d{13})\b", text)
    if m:
        return m.group(1)
    # Cédula/RUC corto solo si el contexto lo menciona explícitamente
    if re.search(r"\b(ruc|cedula|cédula|ci\.?)\b", lower):
        m = re.search(r"\b(\d{10})\b", text)
        if m:
            return m.group(1)
    return None


def extract_phone_from_text(text: str) -> str | None:
    m = re.search(r"\+?593\d{9}", text.replace(" ", ""))
    if m:
        digits = re.sub(r"\D", "", m.group(0))
        return digits if digits.startswith("593") else f"593{digits[-9:]}"
    return None


def is_automated_sender(from_addr: str) -> bool:
    """True si el remitente parece sistema/SRI/facturación automatizada."""
    if not from_addr:
        return True
    lower = from_addr.lower()
    return any(p in lower for p in AUTOMATED_SENDER_PATTERNS)


def human_sender_score(from_addr: str) -> int:
    """Puntos por remitente con aspecto humano (nombre + email personal/corporativo)."""
    if not from_addr or is_automated_sender(from_addr):
        return -50
    score = 0
    if "<" in from_addr and "@" in from_addr:
        display = from_addr.split("<")[0].strip().strip('"')
        if display and "@" not in display and len(display) > 2:
            score += 8
    email_part = from_addr.split("<")[-1].split(">")[0].strip().lower()
    local = email_part.split("@")[0] if "@" in email_part else email_part
    if local and local not in ("info", "admin", "contact", "ventas", "soporte"):
        score += 4
    if re.search(r"\b\d{5,}\b", local):
        score -= 3
    return score


def quote_keyword_hits(text: str) -> int:
    lower = (text or "").lower()
    return sum(1 for w in QUOTE_KEYWORDS if w in lower)


def parse_quote_request_email(subject: str, snippet: str, from_addr: str = "") -> dict[str, Any]:
    combined = f"{subject}\n{snippet}\n{from_addr}"
    lower = combined.lower()
    kw_hits = quote_keyword_hits(combined)
    is_quote = kw_hits > 0
    ruc = extract_ruc_from_text(combined)
    phone = extract_phone_from_text(combined)
    automated = is_automated_sender(from_addr)

    client_hint = ""
    if from_addr and "<" in from_addr:
        client_hint = from_addr.split("<")[0].strip().strip('"')
    elif from_addr and not automated:
        client_hint = from_addr.split("@")[0].replace(".", " ").title()

    amount_match = re.search(r"\$?\s*(\d{1,5}(?:[.,]\d{2})?)\s*(?:usd|dólares|dolares)?", lower)
    amount_hint = amount_match.group(1) if amount_match else None

    summary = "New quote request detected"
    if automated:
        summary = "Automated sender — not a quote request"
    elif ruc and is_quote:
        summary = f"Quote request — tax ID {ruc} in email"
    elif ruc:
        summary = f"Tax ID {ruc} found — possible quote request"
    elif is_quote:
        summary = "Quote request — no tax ID in email (enter manually)"
    else:
        summary = "Low confidence — verify manually"

    return {
        "is_quote_request": (is_quote or bool(ruc)) and not automated,
        "is_automated_sender": automated,
        "quote_keyword_hits": kw_hits,
        "ruc": ruc,
        "phone": phone,
        "client_hint": client_hint,
        "amount_hint": amount_hint,
        "summary": summary,
        "products_hint": _products_hint(lower),
    }


def score_quote_email_candidate(
    mail: dict,
    parsed: dict,
    *,
    is_processed: bool,
) -> int:
    """Mayor puntaje = mejor candidato para demo de cotización."""
    if parsed.get("is_automated_sender"):
        return -100

    score = human_sender_score(mail.get("from_addr", ""))

    kw = int(parsed.get("quote_keyword_hits") or 0)
    score += min(kw * 5, 25)

    if parsed.get("is_quote_request"):
        score += 15
    if parsed.get("ruc"):
        score += 20
    if mail.get("importance") == "alta":
        score += 3
    if is_processed:
        score -= 30
    if mail.get("demo_sample"):
        score -= 40
    if mail.get("mail_id") == "demo-quote-sample":
        score -= 40

    subj = (mail.get("subject") or "").lower()
    if any(w in subj for w in ("sri", "comprobante", "factura electr", "retencion", "autorizacion")):
        score -= 25
    if any(w in subj for w in ("dominio", "no renov", "iess", "coactiva", "regularice")):
        score -= 20
    snippet = (mail.get("snippet") or "").lower()
    if "comprobante" in snippet and "cotiz" not in snippet and "presupuesto" not in snippet:
        score -= 15

    return score


def rank_quote_email_candidates(
    messages: list[dict],
    processed_ids: set[str],
    *,
    limit: int = 3,
    min_score: int = 8,
) -> list[dict[str, Any]]:
    """Devuelve top N candidatos ordenados por relevancia."""
    ranked: list[tuple[int, dict]] = []
    for m in messages:
        parsed = parse_quote_request_email(
            m.get("subject", ""), m.get("snippet", ""), m.get("from_addr", "")
        )
        if parsed.get("is_automated_sender"):
            continue
        mail_id = m.get("mail_id")
        is_processed = bool(m.get("demo_processed_at")) or (mail_id in processed_ids if mail_id else False)
        score = score_quote_email_candidate(m, parsed, is_processed=is_processed)
        if score < min_score and not parsed.get("ruc"):
            continue
        ranked.append((score, {"email": m, "parsed": parsed, "score": score, "already_processed": is_processed}))

    ranked.sort(key=lambda x: x[0], reverse=True)
    return [entry for _, entry in ranked[:limit]]


def _products_hint(lower: str) -> list[str]:
    hints: list[str] = []
    if "poe" in lower or "switch" in lower:
        hints.append("PRD-SW-PoE16")
    if "cámara" in lower or "camara" in lower or "cctv" in lower:
        hints.append("SRV-INST-CAM")
    if "cable" in lower:
        hints.append("SRV-CABLEADO")
    return hints
