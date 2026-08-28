"""Normalización de teléfonos Ecuador / internacional."""

from __future__ import annotations

import re


def normalize_phone(raw: str) -> str:
    digits = "".join(c for c in raw if c.isdigit())
    if not digits:
        return ""
    # Ecuador móvil sin código país: 09xxxxxxxx o 9xxxxxxxx
    if len(digits) == 10 and digits.startswith("09"):
        digits = "593" + digits[1:]
    elif len(digits) == 9 and digits.startswith("9"):
        digits = "593" + digits
    elif len(digits) == 11 and digits.startswith("593"):
        pass
    return digits


def parse_phone_list(*parts: str | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        if not part:
            continue
        if isinstance(part, list):
            chunks = part
        else:
            chunks = re.split(r"[,;\s]+", str(part).strip())
        for chunk in chunks:
            if not chunk:
                continue
            digits = normalize_phone(chunk)
            if len(digits) >= 10 and digits not in seen:
                seen.add(digits)
                out.append(digits)
    return out


def parse_email_list(*parts: str | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        if not part:
            continue
        for chunk in re.split(r"[,;\s]+", str(part).strip()):
            email = chunk.strip().lower()
            if "@" in email and email not in seen:
                seen.add(email)
                out.append(email)
    return out
