"""Guardián de sesión WhatsApp (Evolution) — autonomía sin reinicios ciegos.

Cuando WhatsApp cierra la sesión (`device_removed`, state=close), reiniciar Docker
NO reconecta: hay que re-emparejar. Este módulo detecta, genera QR, alerta por
correo y deja evidencia para el único paso humano ocasional (escaneo QR).
"""

from __future__ import annotations

import base64
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from raphiia_openai import mongo_store
from raphiia_openai.notifications.evolution_client import connection_open
from raphiia_openai.notifications.settings import (
    EVOLUTION_AMD_BASE_URL,
    EVOLUTION_AMD_INSTANCE,
    EVOLUTION_API_KEY,
    EVOLUTION_BASE_URL,
    EVOLUTION_INSTANCE,
)


def _headers() -> dict[str, str]:
    return {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}

GUARDIAN_COL = "ralfia_evolution_session_guardian"
CORE_ROOT = Path(os.environ.get("INNEROS_CORE_ROOT", "/home/rlopez/inneros/inneros_core"))
EVIDENCE_DIR = CORE_ROOT / "var" / "evidence"
OWNER_ALERT_EMAIL = os.environ.get("RALFIA_OWNER_ALERT_EMAIL", "rafagye@gmail.com").strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _nodes() -> list[tuple[str, str, str]]:
    return [
        ("primary", EVOLUTION_BASE_URL, EVOLUTION_INSTANCE),
        ("amd", EVOLUTION_AMD_BASE_URL, EVOLUTION_AMD_INSTANCE),
    ]


def _parse_disconnection(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw[:500]}


def fetch_instance_meta(base: str, name: str) -> dict[str, Any]:
    if not EVOLUTION_API_KEY or not name:
        return {"ok": False, "error": "not_configured"}
    try:
        r = httpx.get(
            f"{base.rstrip('/')}/instance/fetchInstances",
            headers=_headers(),
            timeout=15.0,
        )
        if not r.is_success:
            return {"ok": False, "http_status": r.status_code, "error": r.text[:200]}
        rows = r.json()
        if not isinstance(rows, list):
            return {"ok": False, "error": "invalid_payload"}
        for row in rows:
            if str(row.get("name") or "") == name:
                disc = _parse_disconnection(row.get("disconnectionObject"))
                dtype = ""
                try:
                    dtype = str((disc.get("error") or {}).get("data", {}).get("attrs", {}).get("type") or "")
                except (AttributeError, TypeError):
                    pass
                return {
                    "ok": True,
                    "instance": name,
                    "connection_status": row.get("connectionStatus") or row.get("state"),
                    "disconnection_at": row.get("disconnectionAt"),
                    "disconnection_code": row.get("disconnectionReasonCode"),
                    "disconnection_type": dtype,
                    "owner_jid": row.get("ownerJid"),
                }
        return {"ok": False, "error": "instance_not_found", "instance": name}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def session_needs_pairing(meta: dict[str, Any]) -> bool:
    if not meta.get("ok"):
        return False
    status = str(meta.get("connection_status") or "").lower()
    if status in {"open", "connected"}:
        return False
    dtype = str(meta.get("disconnection_type") or "").lower()
    code = meta.get("disconnection_code")
    if dtype in {"device_removed", "conflict"} or code == 401:
        return True
    return status in {"close", "closed", "disconnected"}


def docker_restart_would_not_help(meta: dict[str, Any]) -> bool:
    return session_needs_pairing(meta)


def _save_qr_png(base64_data: str, instance: str) -> Path | None:
    if not base64_data:
        return None
    raw = base64_data
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    try:
        blob = base64.b64decode(raw)
    except (ValueError, TypeError):
        return None
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = EVIDENCE_DIR / f"evolution-qr-{instance}-{stamp}.png"
    latest = EVIDENCE_DIR / f"evolution-qr-{instance}-latest.png"
    path.write_bytes(blob)
    latest.write_bytes(blob)
    return latest


def request_pairing_qr(base: str, instance: str) -> dict[str, Any]:
    if not EVOLUTION_API_KEY:
        return {"ok": False, "error": "evolution_api_key_missing"}
    try:
        r = httpx.get(
            f"{base.rstrip('/')}/instance/connect/{instance}",
            headers=_headers(),
            timeout=45.0,
        )
        if not r.is_success:
            return {"ok": False, "http_status": r.status_code, "error": r.text[:300]}
        body = r.json()
        qr_path = _save_qr_png(str(body.get("base64") or ""), instance)
        return {
            "ok": True,
            "instance": instance,
            "qr_path": str(qr_path) if qr_path else None,
            "pairing_code": body.get("pairingCode"),
            "has_code": bool(body.get("code")),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def _email_owner_pairing_needed(*, node: str, instance: str, meta: dict[str, Any], qr_path: str | None) -> dict[str, Any]:
    subject = f"[InnerOS] WhatsApp desconectado — escanea QR ({instance})"
    lines = [
        "La sesión WhatsApp/Evolution requiere re-emparejamiento (no se arregla con restart).",
        f"Nodo: {node} · Instancia: {instance}",
        f"Motivo: {meta.get('disconnection_type') or meta.get('connection_status')} (code {meta.get('disconnection_code')})",
        f"Desconectado: {meta.get('disconnection_at') or 'desconocido'}",
    ]
    if qr_path:
        lines.append(f"QR guardado en el servidor: {qr_path}")
    lines.append("En el móvil: WhatsApp → Dispositivos vinculados → Vincular → escanear QR latest.")
    body = "\n".join(lines)
    try:
        from raphiia_openai.notifications import email_client

        return email_client.send_email(
            to_addr=OWNER_ALERT_EMAIL,
            subject=subject,
            body=body,
            from_account="rlopez@pcdoctor.com.ec",
            idempotency_key=f"evolution-pairing:{instance}:{meta.get('disconnection_at') or _now()[:10]}",
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def _persist_state(node: str, payload: dict[str, Any]) -> None:
    db = mongo_store.get_db()
    db[GUARDIAN_COL].update_one(
        {"node": node},
        {"$set": {**payload, "node": node, "updated_at": _now()}},
        upsert=True,
    )


def run_guardian_cycle(*, request_qr: bool = True, email_owner: bool = True) -> dict[str, Any]:
    """Un ciclo: inspeccionar ambos nodos, QR + email si hace falta pairing."""
    report: dict[str, Any] = {"ok": True, "at": _now(), "nodes": []}
    for node, base, instance in _nodes():
        if not instance or not base:
            continue
        open_now = connection_open(instance=instance, node=node)
        meta = fetch_instance_meta(base, instance)
        entry: dict[str, Any] = {
            "node": node,
            "instance": instance,
            "connected": open_now,
            "meta": meta,
            "needs_pairing": session_needs_pairing(meta),
            "skip_docker_restart": docker_restart_would_not_help(meta),
        }
        if entry["needs_pairing"] and request_qr:
            entry["pairing"] = request_pairing_qr(base, instance)
            if email_owner and entry.get("pairing", {}).get("ok"):
                entry["owner_email"] = _email_owner_pairing_needed(
                    node=node,
                    instance=instance,
                    meta=meta,
                    qr_path=(entry.get("pairing") or {}).get("qr_path"),
                )
        _persist_state(node, entry)
        report["nodes"].append(entry)
    report["any_connected"] = any(n.get("connected") for n in report["nodes"])
    report["any_needs_pairing"] = any(n.get("needs_pairing") for n in report["nodes"])
    return report


def evolution_restart_allowed(node: str = "primary") -> tuple[bool, str]:
    """AG-42: no reiniciar Docker si la sesión WA está cerrada por device_removed."""
    base, instance = (EVOLUTION_BASE_URL, EVOLUTION_INSTANCE) if node != "amd" else (EVOLUTION_AMD_BASE_URL, EVOLUTION_AMD_INSTANCE)
    meta = fetch_instance_meta(base, instance or "")
    if docker_restart_would_not_help(meta):
        return False, "whatsapp_session_closed_use_qr_pairing"
    return True, "ok"
