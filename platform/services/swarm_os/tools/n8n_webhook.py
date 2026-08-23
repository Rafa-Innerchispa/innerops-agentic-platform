"""Dispara automatizaciones n8n (correo / WhatsApp)."""

import json

import requests

from config import N8N_WEBHOOK_URL


def notify(payload: dict) -> dict:
    if not N8N_WEBHOOK_URL:
        return {"status": "skipped", "reason": "N8N_WEBHOOK_URL no configurado", "payload": payload}
    try:
        r = requests.post(N8N_WEBHOOK_URL, json=payload, timeout=30)
        return {"status": "sent", "http_status": r.status_code, "body": r.text[:500]}
    except Exception as e:
        return {"status": "error", "message": str(e)}
