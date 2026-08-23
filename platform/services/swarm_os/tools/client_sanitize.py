"""Evita E11000 en clients.ruc por cadenas vacías."""

from __future__ import annotations


def normalize_tax_id_field(value: str | None) -> str:
    return (value or "").strip()


def valid_tax_id(value: str | None) -> bool:
    v = normalize_tax_id_field(value)
    return len(v) >= 10


def sanitize_empty_client_rucs(db) -> int:
    """Mongo sparse unique index treats '' as value — remove all empty strings."""
    res = db.clients.update_many({"ruc": ""}, {"$unset": {"ruc": ""}})
    return int(res.modified_count)
