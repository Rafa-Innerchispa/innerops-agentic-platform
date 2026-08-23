"""
Consulta RUC vía API Intuito/Deuna (SRI).
Requiere credenciales en .env — NO hardcodear usuario/pass del manual.
"""

import json
import re
import time
from typing import Any

import requests

from config import (
    RUC_API_TOKEN_URL,
    RUC_API_USER,
    RUC_API_PASS,
    RUC_API_LOOKUP_URL,
)
from tools.sri_mock import lookup_ruc as mock_lookup

_token_cache: dict[str, Any] = {"token": None, "expires_at": 0.0}


def normalize_tax_id(value: str) -> dict:
    """
    Ecuador:
    - RUC persona natural: cédula (10 dígitos) + 001 = 13 dígitos
    - RUC empresa: 13 dígitos
    """
    clean = re.sub(r"\D", "", value or "")
    if len(clean) == 10:
        return {
            "input": clean,
            "type": "cedula",
            "cedula": clean,
            "ruc": f"{clean}001",
        }
    if len(clean) == 13:
        return {
            "input": clean,
            "type": "ruc",
            "cedula": clean[:10] if clean.endswith("001") else None,
            "ruc": clean,
        }
    return {"input": clean, "type": "unknown", "cedula": None, "ruc": clean}


def _credentials_configured() -> bool:
    return bool(RUC_API_USER and RUC_API_PASS)


def _fetch_token() -> str:
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["token"]

    r = requests.post(
        RUC_API_TOKEN_URL,
        headers={"accept": "application/json", "Content-Type": "application/json"},
        json={"usuario": RUC_API_USER, "pass": RUC_API_PASS},
        timeout=30,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("error"):
        raise RuntimeError(body.get("msgRetorno") or "Error al obtener token RUC")

    token = body.get("data", {}).get("response")
    if not token:
        raise RuntimeError("Token RUC vacío en respuesta")

    _token_cache["token"] = token
    _token_cache["expires_at"] = now + 12 * 3600  # ~12h; la API indica ~1 día variable
    return token


def _parse_ruc_response(ruc: str, api_body: dict) -> dict:
    main = (api_body.get("data") or {}).get("main") or []
    if not main:
        return {
            "ruc": ruc,
            "name": "",
            "address": "",
            "city": "",
            "status": "SIN_DATOS",
            "source": "ruc_api",
            "raw": api_body,
        }
    row = main[0]
    addit = (row.get("addit") or [{}])[0]
    address = addit.get("direccionCompleta", "")
    return {
        "ruc": row.get("numeroRuc", ruc),
        "name": row.get("razonSocial", ""),
        "trade_name": row.get("nombreComercial") or addit.get("nombreFantasiaComercial", ""),
        "legal_rep": row.get("representanteLegal", ""),
        "legal_id": row.get("identificacionLegal", ""),
        "activity": row.get("actividadContribuyente", ""),
        "address": address,
        "city": _guess_city(address),
        "establishment_type": addit.get("tipoEstablecimiento", ""),
        "status": "ACTIVO",
        "source": "ruc_api",
    }


def _guess_city(address: str) -> str:
    if not address:
        return ""
    parts = [p.strip() for p in address.split("/") if p.strip()]
    return parts[1] if len(parts) >= 2 else (parts[0] if parts else "")


def lookup_ruc(value: str, *, allow_mock_fallback: bool = True) -> dict:
    """
    Consulta por RUC o cédula (10 dígitos → RUC persona natural).
    Si no hay credenciales o falla la API, usa mock local.
    """
    norm = normalize_tax_id(value)
    ruc = norm["ruc"]
    if not ruc or len(ruc) != 13:
        return {
            "ruc": ruc,
            "cedula": norm.get("cedula"),
            "name": "",
            "address": "",
            "city": "",
            "status": "ID_INVALIDO",
            "source": "validation",
            "error": "Se requiere RUC de 13 dígitos o cédula de 10 dígitos",
        }

    if not _credentials_configured():
        data = mock_lookup(ruc)
        data["cedula"] = norm.get("cedula")
        data["fallback_reason"] = "RUC_API_USER/RUC_API_PASS no configurados"
        return data

    try:
        token = _fetch_token()
        url = f"{RUC_API_LOOKUP_URL.rstrip('/')}/{ruc}"
        r = requests.get(
            url,
            headers={"accept": "application/json", "Authorization": f"Bearer {token}"},
            timeout=45,
        )
        if r.status_code == 404:
            body = r.json() if r.content else {}
            return {
                "ruc": ruc,
                "cedula": norm.get("cedula"),
                "name": "",
                "address": "",
                "city": "",
                "status": "NO_ENCONTRADO",
                "source": "ruc_api",
                "error": body.get("message", "RUC no válido o información faltante"),
            }
        r.raise_for_status()
        data = _parse_ruc_response(ruc, r.json())
        data["cedula"] = norm.get("cedula")
        return data
    except Exception as e:
        if not allow_mock_fallback:
            raise
        data = mock_lookup(ruc)
        data["cedula"] = norm.get("cedula")
        data["fallback_reason"] = str(e)
        data["source"] = "sri_mock_fallback"
        return data
