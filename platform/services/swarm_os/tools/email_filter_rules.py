"""Reglas de filtro correo — siempre importante vs basura.

Editable en Mongo email_settings.trusted_domains / keywords_important
o ampliar listas aquí. Clasificación: always_important → junk → keywords → ollama.
"""

from __future__ import annotations

import re

# Remitentes / dominios — alerta WhatsApp aunque parezcan newsletter
TRUSTED_DOMAIN_FRAGMENTS = (
    "sri.gob.ec",
    "sri.gov.ec",
    "servicio.net",  # notificaciones SRI frecuentes
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
    "banco central",
    "bce.fin.ec",
)

# Palabras — negocio PC Doctor / finanzas / ventas (es + en)
ALWAYS_IMPORTANT_KEYWORDS = (
    "sri",
    "retención",
    "retencion",
    "ruc",
    "factura electrónica",
    "factura electronica",
    "comprobante",
    "nota de crédito",
    "nota de credito",
    "autorización sri",
    "autorizacion sri",
    "banco",
    "bank",
    "transferencia",
    "depósito",
    "deposito",
    "deposit",
    "abono",
    "pago recibido",
    "payment received",
    "estado de cuenta",
    "extracto bancario",
    "swift",
    "wire transfer",
    "compra",
    "venta",
    "cotización",
    "cotizacion",
    "proforma",
    "presupuesto",
    "orden de compra",
    "purchase order",
    "pedido",
    "invoice",
    "factura",
    "cobro",
    "pago",
    "vencido",
    "vencimiento",
    "mora",
    "proveedor",
    "cliente",
    "contrato",
    "licitación",
    "licitacion",
    "comercialización",
    "comercializacion",
    "importación",
    "importacion",
    "exportación",
    "exportacion",
    "despacho aduanero",
    "aduana",
    "guía de remisión",
    "guia de remision",
    "delivery note",
    "reclamo",
    "urgente",
    "falla",
    "caído",
    "caido",
    "servidor caído",
    "mantenimiento programado",
)

# Basura — solo si NO pasó always_important
JUNK_MARKERS = (
    "unsubscribe",
    "darse de baja",
    "no responder a este",
    "newsletter",
    "mailchimp",
    "sendgrid",
    "hubspot",
    "descuento exclusivo",
    "oferta limitada solo hoy",
    "marketing@",
    "news@",
    "digest@",
    "facebookmail",
    "twitter.com",
    "instagram.com",
    "people you may know",
    "invitación a conectar en linkedin",
    "lotería",
    "loteria",
    "casino",
    "crypto airdrop",
    "has ganado",
    "premio sorpresa",
)

# LinkedIn/GitHub — basura salvo palabras de negocio en asunto
SOCIAL_JUNK_DOMAINS = (
    "linkedin.com",
    "github.com",
    "gitlab.com",
    "google calendar",
    "calendar-notification",
)


def _blob(subject: str, snippet: str, from_addr: str) -> str:
    return f"{subject} {snippet} {from_addr}".lower()


def match_always_important(
    subject: str,
    snippet: str,
    from_addr: str,
    extra_keywords: list[str] | None = None,
    extra_domains: list[str] | None = None,
) -> tuple[bool, str]:
    blob = _blob(subject, snippet, from_addr)
    for dom in TRUSTED_DOMAIN_FRAGMENTS:
        if dom in blob:
            return True, f"dominio confiable ({dom})"
    for dom in extra_domains or []:
        if dom.lower() in blob:
            return True, f"dominio config ({dom})"
    for kw in ALWAYS_IMPORTANT_KEYWORDS:
        if kw.lower() in blob:
            return True, f"negocio ({kw})"
    for kw in extra_keywords or []:
        if kw.lower() in blob:
            return True, f"keyword config ({kw})"
    return False, ""


def match_junk(subject: str, snippet: str, from_addr: str) -> tuple[bool, str]:
    blob = _blob(subject, snippet, from_addr)
    for marker in JUNK_MARKERS:
        if marker in blob:
            return True, marker
    for social in SOCIAL_JUNK_DOMAINS:
        if social in blob:
            # LinkedIn job alerts etc. — no alertar
            if not re.search(r"factura|pago|cotiz|cliente|contrato|urgente", blob, re.I):
                return True, social
    if re.search(r"\bnoreply\b|\bno-reply\b", from_addr, re.I):
        if not re.search(r"sri|banco|factura|pago|transfer|deposit", blob, re.I):
            return True, "noreply sin señal negocio"
    return False, ""
