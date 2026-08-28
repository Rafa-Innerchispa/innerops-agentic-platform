"""Numeración formal RalfIA — separada de Contifico (SRI).

Contifico (legacy ~1 mes): COT-YYYYMM######  ej. COT-202607000206
RalfIA cotizaciones:      PCD-COT-26-######  ej. PCD-COT-26-000035
RalfIA facturas:          reservadas vía Contifico/SRI — no auto-generar aquí
Tickets WhatsApp:         PCD-COT-YYYYMM-XXXX (seguimiento, quote_delivery)

Informes técnicos:        PCD-INF-26-######
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from raphiia_openai import mongo_store

COL_SEQUENCES = "ralfia_document_sequences"

# Prefijos RalfIA (no colisionan con Contifico COT-202608000209)
PREFIXES = {
    "quote": "PCD-COT",
    "technical_report": "PCD-INF",
    "work_order": "PCD-OT",
    "proposal": "PCD-PROP",
}


def _db():
    return mongo_store.get_db()


def _ensure_indexes() -> None:
    db = _db()
    try:
        db[COL_SEQUENCES].create_index([("key", 1)], unique=True, name="ux_doc_seq_key")
    except Exception:
        pass


def _year_suffix(dt: datetime | None = None) -> str:
    return str((dt or datetime.now(timezone.utc)).year)[-2:]


def reserve_document_number(
    doc_type: str = "quote",
    *,
    entity_id: str = "ent_pcdoctor",
    width: int = 3,
) -> dict[str, Any]:
    """Reserva número atómico en Mongo. No reutiliza números."""
    _ensure_indexes()
    doc_type = (doc_type or "quote").strip().lower()
    prefix = PREFIXES.get(doc_type, "PCD-DOC")
    now = datetime.now(timezone.utc)
    yyyy = str(now.year)
    mm = f"{now.month:02d}"
    key = f"{entity_id}:{doc_type}:{yyyy}-{mm}"
    db = _db()
    result = db[COL_SEQUENCES].find_one_and_update(
        {"key": key},
        {
            "$inc": {"seq": 1},
            "$set": {"updated_at": now.isoformat(), "prefix": prefix, "entity_id": entity_id},
            "$setOnInsert": {"created_at": now.isoformat(), "doc_type": doc_type},
        },
        upsert=True,
        return_document=True,
    )
    seq = int((result or {}).get("seq") or 1)
    display_number = f"{prefix}-{yyyy}-{mm}-{seq:0{width}d}"
    return {
        "ok": True,
        "display_number": display_number,
        "sequence": seq,
        "doc_type": doc_type,
        "entity_id": entity_id,
        "namespace": "ralfia",
        "contifico_compatible": False,
    }


def peek_next_number(doc_type: str = "quote", *, entity_id: str = "ent_pcdoctor", width: int = 3) -> dict[str, Any]:
    _ensure_indexes()
    now = datetime.now(timezone.utc)
    yyyy = str(now.year)
    mm = f"{now.month:02d}"
    key = f"{entity_id}:{doc_type}:{yyyy}-{mm}"
    doc = _db()[COL_SEQUENCES].find_one({"key": key}) or {}
    seq = int(doc.get("seq") or 0) + 1
    prefix = PREFIXES.get(doc_type, "PCD-DOC")
    return {
        "ok": True,
        "next_display_number": f"{prefix}-{yyyy}-{mm}-{seq:0{width}d}",
        "last_sequence": int(doc.get("seq") or 0),
    }
