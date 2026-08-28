"""Cliente Evolution API v2 — WhatsApp."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from config import EVOLUTION_API_KEY, EVOLUTION_BASE_URL, EVOLUTION_INSTANCE


def _headers() -> dict[str, str]:
    return {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}


def _base() -> str:
    return EVOLUTION_BASE_URL.rstrip("/")


def evolution_available() -> bool:
    try:
        r = requests.get(f"{_base()}/", timeout=5)
        return r.status_code < 500
    except Exception:
        return False


def evolution_info() -> dict[str, Any]:
    r = requests.get(f"{_base()}/", timeout=5)
    return r.json() if r.ok else {"error": r.text[:200]}


def list_instances() -> list[dict[str, Any]]:
    r = requests.get(f"{_base()}/instance/fetchInstances", headers=_headers(), timeout=15)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else data.get("instances", [])


def delete_instance(name: str) -> dict[str, Any]:
    r = requests.delete(f"{_base()}/instance/delete/{name}", headers=_headers(), timeout=30)
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text[:300]}
    return {"ok": r.ok, "http_status": r.status_code, "data": body}


def check_number(instance: str, number: str) -> dict[str, Any]:
    digits = "".join(c for c in number if c.isdigit())
    r = requests.post(
        f"{_base()}/chat/whatsappNumbers/{instance}",
        headers=_headers(),
        json={"numbers": [digits]},
        timeout=15,
    )
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text[:300]}
    exists = False
    if isinstance(body, list) and body:
        exists = bool(body[0].get("exists"))
    return {"ok": r.ok, "exists": exists, "data": body, "number": digits}


def create_instance(name: str) -> dict[str, Any]:
    r = requests.post(
        f"{_base()}/instance/create",
        headers=_headers(),
        json={"instanceName": name, "integration": "WHATSAPP-BAILEYS", "qrcode": True},
        timeout=60,
    )
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text[:500]}
    return {"ok": r.ok, "http_status": r.status_code, "data": body}


def connect_instance(name: str) -> dict[str, Any]:
    r = requests.get(f"{_base()}/instance/connect/{name}", headers=_headers(), timeout=60)
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text[:500]}
    return {"ok": r.ok, "http_status": r.status_code, "data": body}


def connection_state(name: str) -> dict[str, Any]:
    r = requests.get(f"{_base()}/instance/connectionState/{name}", headers=_headers(), timeout=15)
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text[:500]}
    return {"ok": r.ok, "state": body}


def _instance_is_open(name: str) -> tuple[bool, str]:
    try:
        for inst in list_instances():
            if inst.get("name") == name or inst.get("instanceName") == name:
                st = inst.get("connectionStatus") or inst.get("state") or ""
                owner = (inst.get("ownerJid") or "").split("@")[0]
                return st == "open", owner
        st = connection_state(name).get("state", {})
        if isinstance(st, dict):
            inner = (st.get("instance") or {}).get("state") or st.get("state") or ""
            return inner == "open", ""
        return False, ""
    except Exception:
        return False, ""


def resolve_connected_instance(preferred: str | None = None) -> tuple[str | None, str]:
    """Devuelve (nombre_instancia, nota). Prefiere la conectada (open)."""
    try:
        open_names: list[str] = []
        for inst in list_instances():
            name = inst.get("name") or inst.get("instanceName") or ""
            if not name:
                continue
            st = inst.get("connectionStatus") or inst.get("state") or ""
            if st == "open":
                open_names.append(name)
                if preferred and name == preferred:
                    return name, "preferred_open"
        if open_names:
            pick = open_names[0]
            if preferred and preferred not in open_names:
                return pick, f"fallback_open (configured «{preferred}» offline)"
            return pick, "auto_open"
        if preferred:
            return preferred, "configured_not_verified"
    except Exception as e:
        if preferred:
            return preferred, f"list_failed:{e}"
    return None, "no_instance"


def send_whatsapp(number: str, text: str, instance: str | None = None, *, skip_existence_check: bool = False) -> dict[str, Any]:
    pref = instance or EVOLUTION_INSTANCE
    inst, inst_note = resolve_connected_instance(pref)
    if not inst:
        return {"status": "error", "message": "No Evolution instance configured", "instance_note": inst_note}
    digits = "".join(c for c in number if c.isdigit())
    if not digits:
        return {"status": "error", "message": "número WhatsApp inválido"}

    is_open, linked = _instance_is_open(inst)
    if not is_open:
        return {
            "status": "error",
            "message": f"Instance «{inst}» not connected (must be open). Server account: {linked or '—'}",
            "linked_number": linked,
            "instance_note": inst_note,
            "hint": "Open Email module → WhatsApp card → connect QR, or set EVOLUTION_INSTANCE in .env",
        }

    chk = check_number(inst, digits)
    if chk.get("ok") and not chk.get("exists") and not skip_existence_check:
        return {"status": "error", "message": f"El número {digits} no tiene WhatsApp activo", "check": chk}
    if chk.get("ok") and not chk.get("exists") and skip_existence_check:
        pass  # hackathon: intentar envío igual (Evolution a veces marca false)

    try:
        r = requests.post(
            f"{_base()}/message/sendText/{inst}",
            headers=_headers(),
            json={"number": digits, "text": text[:4000], "delay": 800},
            timeout=25,
        )
    except requests.exceptions.Timeout:
        return {
            "status": "error",
            "message": (
                "Evolution no respondió a tiempo. Suele ser Redis desconectado — "
                "reinicia Evolution: cd ~/evolution-api && docker compose up -d"
            ),
        }
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": str(e)}

    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text[:500]}
    return {
        "status": "sent" if r.ok else "error",
        "http_status": r.status_code,
        "response": body,
        "number": digits,
        "instance": inst,
        "instance_note": inst_note,
        "message": body.get("message") if isinstance(body, dict) and not r.ok else None,
    }


def _prepare_whatsapp_recipient(
    number: str, instance: str | None = None, *, skip_existence_check: bool = False
) -> tuple[str | None, str, str, dict[str, Any] | None]:
    """Devuelve (inst, digits, inst_note, error_dict)."""
    pref = instance or EVOLUTION_INSTANCE
    inst, inst_note = resolve_connected_instance(pref)
    if not inst:
        return None, "", inst_note, {"status": "error", "message": "No Evolution instance configured", "instance_note": inst_note}
    digits = "".join(c for c in number if c.isdigit())
    if not digits:
        return inst, "", inst_note, {"status": "error", "message": "número WhatsApp inválido"}
    is_open, linked = _instance_is_open(inst)
    if not is_open:
        return inst, digits, inst_note, {
            "status": "error",
            "message": f"Instance «{inst}» not connected (must be open). Server account: {linked or '—'}",
            "linked_number": linked,
            "instance_note": inst_note,
        }
    chk = check_number(inst, digits)
    if chk.get("ok") and not chk.get("exists") and not skip_existence_check:
        return inst, digits, inst_note, {
            "status": "error",
            "message": f"El número {digits} no tiene WhatsApp activo",
            "check": chk,
        }
    return inst, digits, inst_note, None


def send_whatsapp_document(
    number: str,
    file_path: str | Path,
    caption: str = "",
    instance: str | None = None,
    file_name: str | None = None,
    mimetype: str | None = None,
    *,
    skip_existence_check: bool = False,
) -> dict[str, Any]:
    """Envía documento (.pdf, .txt, etc.) por WhatsApp vía Evolution sendMedia."""
    import base64

    path = Path(file_path)
    if not path.is_file():
        return {"status": "error", "message": f"Archivo no encontrado: {path}"}

    inst, digits, inst_note, err = _prepare_whatsapp_recipient(
        number, instance, skip_existence_check=skip_existence_check
    )
    if err:
        return err

    raw = path.read_bytes()
    if len(raw) > 15_000_000:
        return {"status": "error", "message": "Archivo demasiado grande para WhatsApp"}

    fname = file_name or path.name
    mime = mimetype or _guess_mimetype(path, fname)
    b64 = base64.b64encode(raw).decode("ascii")

    try:
        r = requests.post(
            f"{_base()}/message/sendMedia/{inst}",
            headers=_headers(),
            json={
                "number": digits,
                "mediatype": "document",
                "mimetype": mime,
                "fileName": fname,
                "caption": (caption or "")[:900],
                "media": b64,
                "delay": 800,
            },
            timeout=60,
        )
    except requests.exceptions.Timeout:
        return {"status": "error", "message": "Evolution timeout enviando documento"}
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": str(e)}

    try:
        body = r.json()
    except Exception:
        body = {"raw": (r.text or "")[:500]}

    err_msg: str | None = None
    if not r.ok:
        if isinstance(body, dict):
            raw_msg = body.get("message") or body.get("error")
            if isinstance(raw_msg, list):
                err_msg = "; ".join(str(x) for x in raw_msg)
            elif raw_msg:
                err_msg = str(raw_msg)
        if not err_msg:
            err_msg = f"HTTP {r.status_code}"

    return {
        "status": "sent" if r.ok else "error",
        "http_status": r.status_code,
        "response": body,
        "number": digits,
        "instance": inst,
        "instance_note": inst_note,
        "file": fname,
        "message": err_msg,
    }


def _guess_mimetype(path: Path, file_name: str) -> str:
    ext = Path(file_name).suffix.lower() or path.suffix.lower()
    return {
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".md": "text/plain",
        ".json": "application/json",
    }.get(ext, "application/octet-stream")
