"""Validaciones de campos para admin."""

from __future__ import annotations

import re

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_EC_RE = re.compile(r"^\+593\d{9}$")
RUC_EC_RE = re.compile(r"^\d{10}(\d{3})?$")


def validate_email(value: str) -> str | None:
    v = (value or "").strip()
    if not v:
        return None
    if not EMAIL_RE.match(v):
        return "Email inválido (debe tener @ y dominio con punto)"
    return None


def validate_phone_ec(value: str) -> str | None:
    v = (value or "").strip().replace(" ", "")
    if not v:
        return None
    if not v.startswith("+"):
        if v.startswith("0"):
            v = "+593" + v[1:]
        elif len(v) == 9:
            v = "+593" + v
    if not PHONE_EC_RE.match(v):
        return "Teléfono Ecuador: formato +593999059000 (9 dígitos tras +593)"
    return None


def normalize_phone_ec(value: str) -> str:
    v = (value or "").strip().replace(" ", "")
    if not v:
        return ""
    if v.startswith("+"):
        return v
    if v.startswith("0") and len(v) == 10:
        return "+593" + v[1:]
    if len(v) == 9:
        return "+593" + v
    return v


def validate_ruc_cedula(value: str) -> str | None:
    clean = re.sub(r"\D", "", value or "")
    if not clean:
        return "RUC o cédula es obligatorio"
    if len(clean) not in (10, 13):
        return "Cédula 10 dígitos o RUC 13 dígitos"
    return None
