"""Typed bridge from Evolution WhatsApp events to QuoteOps IESS actions."""

from __future__ import annotations

import os
import re
from typing import Any

import httpx

from raphiia_openai import whatsapp_evolution_parse as evo
from raphiia_openai.notifications.evolution_client import get_media_base64


IESS_PAYMENT_RE = re.compile(r"\b(?:pago|pague|pagu[eé]|pagando)\s+(?:de[l]?\s+)?iess?\b", re.I)
IESS_CONFIRM_RE = re.compile(r"^\s*confirmar\s+pago\s+(iesspay_[a-f0-9]{16})\s*$", re.I)
IESS_CANCEL_RE = re.compile(r"^\s*cancelar\s+pago\s+(iesspay_[a-f0-9]{16})\s*$", re.I)
QUOTEOPS_URL = os.getenv("RALPHIIA_QUOTEOPS_URL", "http://127.0.0.1:8765").rstrip("/")


def _message_object(payload: dict[str, Any]) -> dict[str, Any]:
    data = evo.evolution_data(payload)
    message = data.get("message") if isinstance(data, dict) else None
    return message if isinstance(message, dict) else {}


def is_iess_payment_image(payload: dict[str, Any], message: str) -> bool:
    return bool(IESS_PAYMENT_RE.search(message or "") and isinstance(_message_object(payload).get("imageMessage"), dict))


def extract_message_id(payload: dict[str, Any]) -> str:
    data = evo.evolution_data(payload)
    key = data.get("key") if isinstance(data, dict) else None
    return str((key or {}).get("id") or "").strip()


def parse_iess_action(message: str) -> tuple[str, str] | None:
    confirm = IESS_CONFIRM_RE.match(message or "")
    if confirm:
        return "confirm", confirm.group(1).lower()
    cancel = IESS_CANCEL_RE.match(message or "")
    if cancel:
        return "cancel", cancel.group(1).lower()
    return None


def preview_iess_payment(payload: dict[str, Any], *, sender: str, node: str) -> dict[str, Any]:
    message_id = extract_message_id(payload)
    if not message_id:
        return {"ok": False, "status": "needs_clarification", "reply": "Recibí la imagen, pero Evolution no entregó su identificador. Reenvíala con el texto Pago IESS."}
    try:
        encoded = get_media_base64(payload, node=node)
        response = httpx.post(
            f"{QUOTEOPS_URL}/api/iess/whatsapp-preview",
            json={
                "image_base64": encoded,
                "message_id": message_id,
                "sender": sender,
                "caption": evo.extract_message(payload),
            },
            timeout=45.0,
        )
        response.raise_for_status()
        result = response.json()
        if isinstance(result, dict):
            return result
    except Exception:
        pass
    return {
        "ok": False,
        "status": "temporarily_unavailable",
        "reply": "Identifiqué que es un pago IESS, pero no pude leer la imagen ahora. No registré nada. Reintenta en unos minutos o escribe planilla, monto y comprobante.",
    }


def apply_iess_action(action: str, action_id: str, *, sender: str) -> dict[str, Any]:
    endpoint = "confirm" if action == "confirm" else "cancel"
    try:
        response = httpx.post(
            f"{QUOTEOPS_URL}/api/iess/{endpoint}",
            json={"action_id": action_id, "approved_by": "RAFAEL_WHATSAPP", "request_sender": sender},
            timeout=15.0,
        )
        response.raise_for_status()
        result = response.json()
        if isinstance(result, dict):
            return result
    except Exception:
        pass
    return {"ok": False, "error": "quoteops_temporarily_unavailable"}


def format_action_reply(action: str, result: dict[str, Any]) -> str:
    if not result.get("ok"):
        if result.get("error") == "sender_not_authorized_for_action":
            return "No puedo ejecutar esa acción desde este número."
        return "No pude procesar la acción IESS. No cambié ningún registro."
    if result.get("status") == "already_confirmed":
        return f"Ese pago IESS ya estaba registrado como {result.get('payment_id')}; no lo dupliqué."
    if action == "cancel":
        return "Cancelé el borrador del pago IESS. No se registró ningún movimiento contable."
    return (
        f"Pago IESS registrado: USD {float(result.get('amount') or 0):.2f}.\n"
        f"Planilla: {result.get('plan_code') or 'N/D'}\n"
        f"Movimiento: {result.get('payment_id') or 'N/D'}\n"
        "La evidencia quedó vinculada y un reenvío no duplicará el pago."
    )
