"""Schema estricto Memory Records — enterprise VKR (Verifiable Knowledge Records)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RECORD_TYPES = frozenset(
    {
        "person",
        "organization",
        "address",
        "contact",
        "financial_account",
        "identifier",
        "contract",
        "decision",
        "process",
        "asset",
        "quote",
        "invoice",
        "social_profile",
        "other",
    }
)
SUBJECT_ROLES = frozenset(
    {"owner", "client", "vendor", "employee", "company", "contact", "unknown"}
)
EPISTEMIC = frozenset({"fact", "decision", "intention", "projection", "hypothesis", "summary"})
VERIFICATION = frozenset({"extracted", "review", "canonical", "rejected", "duplicate"})
DOC_CLASSES = frozenset(
    {"cotizacion", "factura", "informe", "contrato", "foto", "correspondencia", "contabilidad", "legal", "other"}
)
BRANDS = frozenset({"pcdoctor", "domotika", "innerchispa", "iskcon", "ralfia", "general"})

# Atributos permitidos por tipo — evita "Dirección" genérico sin contexto
ATTRIBUTE_CATALOG: dict[str, frozenset[str]] = {
    "address": frozenset(
        {"billing_address", "shipping_address", "service_site", "registered_address", "mailing_address", "other_address"}
    ),
    "contact": frozenset({"email", "phone", "mobile", "whatsapp", "website", "other_contact"}),
    "financial_account": frozenset({"bank_account", "tax_id", "payment_reference", "invoice_number", "other_financial"}),
    "identifier": frozenset({"tax_id", "ruc", "cedula", "passport", "license", "domain", "other_id"}),
    "social_profile": frozenset({"linkedin", "facebook", "instagram", "twitter", "other_social"}),
    "person": frozenset({"full_name", "role", "other_person"}),
    "organization": frozenset({"legal_name", "trade_name", "other_org"}),
    "quote": frozenset({"quote_number", "amount", "valid_until", "other_quote"}),
    "invoice": frozenset({"invoice_number", "amount", "due_date", "other_invoice"}),
}

MIN_CONFIDENCE_STAGING = 0.55
MIN_CONFIDENCE_CANONICAL = 0.78
MEDIA_EXT = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".mp4", ".mov"})


@dataclass
class PathHierarchy:
    source_path: str
    brand: str = "general"
    client_name: str | None = None
    year: int | None = None
    doc_class: str = "other"
    is_media_only: bool = False
    priority: int = 0  # mayor = procesar primero

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "brand": self.brand,
            "client_name": self.client_name,
            "year": self.year,
            "doc_class": self.doc_class,
            "is_media_only": self.is_media_only,
            "priority": self.priority,
        }


def parse_path_hierarchy(source_path: str) -> PathHierarchy:
    p = source_path.replace("\\", "/")
    low = p.lower()
    h = PathHierarchy(source_path=source_path)

    if "pc-doctor" in low or "pcdoctor" in low:
        h.brand = "pcdoctor"
        h.priority = 100
        m = re.search(r"/clientes/([^/]+)", low)
        if m:
            h.client_name = m.group(1).replace("%20", " ").strip().title()
            h.priority = 120
    elif "domotika" in low:
        h.brand = "domotika"
        h.priority = 80
    elif "innerchispa" in low or "innerspark" in low:
        h.brand = "innerchispa"
        h.priority = 70
    elif "iskcon" in low:
        h.brand = "iskcon"
        h.priority = 60
    elif "notion_export" in low:
        h.brand = "ralfia"
        h.priority = 90

    for token in ("cotizaciones", "cotizacion", "quote"):
        if token in low:
            h.doc_class = "cotizacion"
            break
    else:
        for token, cls in (
            ("facturas", "factura"),
            ("factura", "factura"),
            ("informes", "informe"),
            ("informe", "informe"),
            ("contrato", "contrato"),
            ("fotos", "foto"),
            ("photos", "foto"),
        ):
            if token in low:
                h.doc_class = cls
                break

    ym = re.search(r"(20\d{2})", p)
    if ym:
        h.year = int(ym.group(1))

    ext = Path(source_path).suffix.lower()
    if ext in MEDIA_EXT and h.doc_class == "other":
        h.is_media_only = True
        h.doc_class = "foto"

    return h


def normalize_value(record_type: str, attribute: str, raw: str) -> str:
    v = re.sub(r"\s+", " ", (raw or "").strip())
    if record_type == "contact" and attribute == "email":
        v = v.lower()
    if record_type == "social_profile" and "linkedin" in attribute:
        m = re.search(r"linkedin\.com/in/[\w\-]+", v, re.I)
        if m:
            v = "https://www." + m.group(0).lower().lstrip("www.")
    return v[:500]


def record_fingerprint(
    *,
    tenant_id: str,
    brand: str,
    client_name: str | None,
    record_type: str,
    attribute: str,
    subject_role: str,
    subject_name: str,
    value_normalized: str,
) -> str:
    parts = "|".join(
        [
            tenant_id,
            brand,
            (client_name or "").lower(),
            record_type,
            attribute,
            subject_role,
            subject_name.lower()[:80],
            value_normalized.lower()[:200],
        ]
    )
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


def validate_record(raw: dict[str, Any], hierarchy: PathHierarchy) -> tuple[dict[str, Any] | None, str | None]:
    record_type = str(raw.get("record_type") or "other").strip().lower()
    if record_type not in RECORD_TYPES:
        record_type = "other"

    attribute = str(raw.get("attribute") or "other").strip().lower()
    allowed = ATTRIBUTE_CATALOG.get(record_type)
    if allowed and attribute not in allowed:
        attribute = next(iter(allowed)) if len(allowed) == 1 else f"other_{record_type}"

    subject_role = str(raw.get("subject_role") or "unknown").strip().lower()
    if subject_role not in SUBJECT_ROLES:
        subject_role = "unknown"

    subject_name = str(raw.get("subject_name") or "").strip()[:200]
    if hierarchy.client_name and subject_role in {"unknown", "client"}:
        subject_role = "client"
        if not subject_name:
            subject_name = hierarchy.client_name

    value_raw = str(raw.get("value_raw") or raw.get("value") or "").strip()
    value_normalized = normalize_value(record_type, attribute, str(raw.get("value_normalized") or value_raw))
    if len(value_normalized) < 3:
        return None, "value_too_short"

    try:
        confidence = float(raw.get("confidence") or 0.5)
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    epistemic = str(raw.get("epistemic_class") or "fact").strip().lower()
    if epistemic not in EPISTEMIC:
        epistemic = "fact"

    # Gate: datos de contacto/dirección sin sujeto claro → review, no canonical automático
    needs_subject = record_type in {"address", "contact", "financial_account", "identifier"}
    if needs_subject and subject_role == "unknown" and not hierarchy.client_name:
        if confidence < 0.85:
            return None, "subject_unknown_low_confidence"

    if confidence < MIN_CONFIDENCE_STAGING:
        return None, "confidence_below_staging"

    return {
        "record_type": record_type,
        "attribute": attribute,
        "subject_role": subject_role,
        "subject_name": subject_name or hierarchy.client_name or "unknown",
        "value_normalized": value_normalized,
        "value_raw": value_raw[:800],
        "confidence": confidence,
        "epistemic_class": epistemic,
        "hierarchy": hierarchy.to_dict(),
    }, None


def auto_verification_status(rec: dict[str, Any]) -> str:
    """Reglas de promoción a canonical sin owner manual."""
    if rec.get("epistemic_class") in {"projection", "hypothesis", "intention"}:
        return "review"

    conf = float(rec.get("confidence") or 0)
    rt = rec.get("record_type")
    attr = rec.get("attribute")
    hier = rec.get("hierarchy") or {}
    brand = hier.get("brand")
    client = hier.get("client_name")
    doc_class = hier.get("doc_class")

    if rt == "social_profile" and "linkedin.com/in/" in str(rec.get("value_normalized", "")):
        return "canonical"

    if brand == "pcdoctor" and client and doc_class in {"cotizacion", "factura", "informe", "contrato"}:
        if conf >= MIN_CONFIDENCE_CANONICAL and rt in {"quote", "invoice", "organization", "contact", "identifier"}:
            return "canonical"
        if conf >= MIN_CONFIDENCE_STAGING:
            return "review"

    if hier.get("brand") == "ralfia" and rt in {"social_profile", "process", "decision"} and conf >= 0.82:
        return "canonical"

    if conf >= MIN_CONFIDENCE_CANONICAL and rt in {"identifier", "social_profile"}:
        return "canonical"

    return "extracted" if conf >= MIN_CONFIDENCE_STAGING else "rejected"
