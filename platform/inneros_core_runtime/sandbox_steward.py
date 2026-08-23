"""Sandbox IA — propuestas destructivas (borrar/mover modelos) con aprobación WhatsApp."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import mongo_store

COLLECTION = "ralfia_sandbox_steward_proposals"
STATE_DIR = Path(os.getenv("RALPHI_DATA_ROOT", "/home/rlopez/data")) / "ralfia"
LOG_FILE = STATE_DIR / "sandbox_steward.log"

SANDBOX_OLLAMA_AMD = os.getenv("SANDBOX_OLLAMA_AMD", "127.0.0.1:11436")
SANDBOX_OLLAMA_INTEL = os.getenv("SANDBOX_OLLAMA_INTEL", "192.168.1.4:11435")
SANDBOX_MODELS_ROOT_AMD = Path(
    os.getenv("SANDBOX_MODELS_ROOT_AMD", "/home/rlopez/data/ollama-sandbox-amd/models")
)

PROTECTED_MODEL_PREFIXES = (
    "qwen:",
    "mistral:",
    "llava:",
    "nomic-embed",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(msg: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now().strftime('%F %T')}] {msg}\n"
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line)


def _proposal_id() -> str:
    return f"sm_{secrets.token_hex(3)}"


def _ollama_host(node: str) -> str:
    return SANDBOX_OLLAMA_INTEL if node == "intel" else SANDBOX_OLLAMA_AMD


def list_sandbox_models(*, node: str = "amd") -> dict[str, Any]:
    host = _ollama_host(node)
    try:
        out = subprocess.check_output(
            ["ollama", "list"],
            env={**os.environ, "OLLAMA_HOST": host},
            text=True,
            timeout=30,
        )
        models: list[dict[str, str]] = []
        for line in out.strip().splitlines()[1:]:
            parts = line.split()
            if parts:
                models.append({"name": parts[0], "raw": line.strip()})
        return {"ok": True, "node": node, "host": host, "models": models}
    except Exception as exc:
        return {"ok": False, "node": node, "host": host, "error": str(exc)}


def notify_owner(
    message: str,
    *,
    severity: str = "info",
    interactive: list[dict[str, str]] | None = None,
    proposal_id: str | None = None,
) -> dict[str, Any]:
    """Notifica a Rafael cualquier evento del sandbox (info/warn/critical)."""
    from raphiia_openai.notifications.evolution_client import send_whatsapp, send_whatsapp_interactive

    prefix = {"info": "ℹ️", "warn": "⚠️", "critical": "🚨"}.get(severity, "ℹ️")
    text = f"{prefix} *Sandbox IA · AMD*\n{message.strip()}"
    if proposal_id:
        text += f"\n\nResponde:\n`confirmar sandbox {proposal_id}`\n`cancelar sandbox {proposal_id}`"
    try:
        if interactive:
            return send_whatsapp_interactive(text, interactive, footer="Sandbox Steward")
        return send_whatsapp(text)
    except Exception as exc:
        _log(f"notify_failed: {exc}")
        return {"ok": False, "error": str(exc)}


def propose_delete_model(
    model_name: str,
    *,
    node: str = "amd",
    reason: str | None = None,
    requested_by: str = "agent",
) -> dict[str, Any]:
    model_name = model_name.strip()
    if not model_name:
        return {"ok": False, "error": "empty_model"}
    if any(model_name.startswith(p) for p in PROTECTED_MODEL_PREFIXES):
        return {"ok": False, "error": "protected_productive_model", "model": model_name}

    listing = list_sandbox_models(node=node)
    names = {m["name"] for m in listing.get("models") or []}
    if model_name not in names:
        return {"ok": False, "error": "model_not_found", "model": model_name, "available": sorted(names)}

    pid = _proposal_id()
    doc = {
        "proposal_id": pid,
        "op": "ollama_rm",
        "model": model_name,
        "node": node,
        "ollama_host": _ollama_host(node),
        "status": "pending_approval",
        "reason": reason or f"Borrar modelo sandbox `{model_name}`",
        "requested_by": requested_by,
        "created_at": _now(),
        "updated_at": _now(),
    }
    mongo_store.get_db()[COLLECTION].insert_one(doc)
    doc.pop("_id", None)

    msg = (
        f"*Propuesta borrar modelo*\n"
        f"Modelo: `{model_name}`\n"
        f"Nodo: {node} ({doc['ollama_host']})\n"
        f"Motivo: {doc['reason']}\n"
        f"Solicitado por: {requested_by}\n\n"
        f"¿Autorizas borrar este modelo?\n"
        f"ID: `{pid}`"
    )
    notify = notify_owner(
        msg,
        severity="warn",
        proposal_id=pid,
        interactive=[
            {"id": f"sandbox.confirm.{pid}", "label": "Sí, borrar"},
            {"id": f"sandbox.cancel.{pid}", "label": "No borrar"},
        ],
    )
    _log(f"PROPOSE_DELETE {model_name} pid={pid} by={requested_by}")
    return {"ok": True, "proposal": doc, "notify": notify}


def confirm_delete(sender: str, proposal_id: str) -> dict[str, Any]:
    from raphiia_openai import whatsapp_identity

    identity = whatsapp_identity.resolve_identity(sender)
    if not whatsapp_identity.is_owner(identity):
        return {"ok": False, "error": "unauthorized", "text": "Solo el owner puede autorizar borrados."}

    db = mongo_store.get_db()
    doc = db[COLLECTION].find_one({"proposal_id": proposal_id, "status": "pending_approval"}, {"_id": 0})
    if not doc:
        return {"ok": False, "error": "not_found", "text": f"No hay propuesta pendiente `{proposal_id}`."}

    model = doc["model"]
    host = doc.get("ollama_host") or _ollama_host(doc.get("node", "amd"))
    try:
        subprocess.check_call(
            ["ollama", "rm", model],
            env={**os.environ, "OLLAMA_HOST": host},
            timeout=120,
        )
        ok = True
        err = None
        _log(f"DELETED {model} host={host} by={sender}")
    except subprocess.CalledProcessError as exc:
        ok = False
        err = str(exc)
        _log(f"DELETE_FAILED {model} host={host} err={err}")

    status = "executed" if ok else "failed"
    db[COLLECTION].update_one(
        {"proposal_id": proposal_id},
        {
            "$set": {
                "status": status,
                "executed_at": _now(),
                "executed_by": sender,
                "result": {"ok": ok, "error": err},
            }
        },
    )
    if ok:
        text = f"✅ Modelo `{model}` borrado del sandbox ({host}). ID `{proposal_id}`."
    else:
        text = f"❌ No se pudo borrar `{model}`: {err}"
    notify_owner(text, severity="info" if ok else "critical")
    return {"ok": ok, "model": model, "text": text, "error": err}


def cancel_delete(sender: str, proposal_id: str) -> dict[str, Any]:
    from raphiia_openai import whatsapp_identity

    identity = whatsapp_identity.resolve_identity(sender)
    if not whatsapp_identity.is_owner(identity):
        return {"ok": False, "error": "unauthorized"}
    db = mongo_store.get_db()
    r = db[COLLECTION].update_one(
        {"proposal_id": proposal_id, "status": "pending_approval"},
        {"$set": {"status": "cancelled", "cancelled_at": _now(), "cancelled_by": sender}},
    )
    if r.matched_count == 0:
        return {"ok": False, "text": f"No había propuesta pendiente `{proposal_id}`."}
    _log(f"CANCELLED {proposal_id} by={sender}")
    return {"ok": True, "text": f"Cancelado `{proposal_id}`. No se borró nada."}


def handle_button(button_id: str, sender: str) -> dict[str, Any] | None:
    import re

    m = re.fullmatch(r"sandbox\.confirm\.(sm_[a-f0-9]+)", button_id)
    if m:
        return confirm_delete(sender, m.group(1))
    m = re.fullmatch(r"sandbox\.cancel\.(sm_[a-f0-9]+)", button_id)
    if m:
        return cancel_delete(sender, m.group(1))
    return None


def build_status(*, node: str = "amd") -> dict[str, Any]:
    listing = list_sandbox_models(node=node)
    pending = list(
        mongo_store.get_db()[COLLECTION].find({"status": "pending_approval"}, {"_id": 0}).limit(20)
    )
    return {
        "schema": "ralfia.sandbox_steward.v1",
        "timestamp": _now(),
        "hostname": os.uname().nodename,
        "node": node,
        "ollama": listing,
        "pending_proposals": pending,
        "policy": "Ningún borrado/movimiento destructivo sin confirmación WhatsApp del owner.",
    }
