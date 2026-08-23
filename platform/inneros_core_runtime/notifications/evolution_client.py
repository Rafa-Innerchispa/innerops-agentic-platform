"""Evolution API — WhatsApp directo (sin n8n)."""

from __future__ import annotations

import os
import socket
from typing import Any

import httpx

from raphiia_openai.notifications.settings import (
    EVOLUTION_AMD_BASE_URL,
    EVOLUTION_AMD_INSTANCE,
    EVOLUTION_API_KEY,
    EVOLUTION_BASE_URL,
    EVOLUTION_DEFAULT_NODE,
    EVOLUTION_INSTANCE,
    NOTIFY_WHATSAPP_TO,
    WHATSAPP_AMD_SEND_ENABLED,
    WHATSAPP_AMD_STATUS_ENABLED,
    WHATSAPP_STATUS_ENABLED,
)


def resolve_inbound_node(payload: dict[str, Any] | None = None, *, instance: str | None = None) -> str:
    """Resuelve nodo Evolution para responder al mismo chip que recibió el mensaje."""
    inst = (
        instance
        or (payload or {}).get("instance")
        or (payload or {}).get("whatsappInstance")
        or (payload or {}).get("id")
        or ""
    ).strip()
    inst_lower = inst.lower()
    amd_name = (EVOLUTION_AMD_INSTANCE or "").strip().lower()
    primary_name = (EVOLUTION_INSTANCE or "").strip().lower()
    if amd_name and inst_lower == amd_name:
        return "amd"
    if primary_name and inst_lower == primary_name:
        return "primary"
    server = str((payload or {}).get("server_url") or (payload or {}).get("serverUrl") or "").lower()
    if "192.168.1.5" in server or ":8082" in server and "1.5" in server:
        return "amd"
    if "innerchispa" in inst_lower or "chispa" in inst_lower:
        return "amd"
    if "amd" in inst_lower or "backup" in inst_lower:
        return "amd"
    if "pcdoctor" in inst_lower or "ralph" in inst_lower:
        return "primary"
    return (EVOLUTION_DEFAULT_NODE or "primary").strip().lower() or "primary"


def local_node() -> str:
    """Nodo local: amd (.5) o primary (.4)."""
    explicit = os.getenv("RALFIA_NODE", "").strip().lower()
    if explicit in ("amd", "backup", "5", ".5"):
        return "amd"
    if explicit in ("primary", "intel", "4", ".4"):
        return "primary"
    host = socket.gethostname().lower()
    if "amd" in host or "ralphiiaamd" in host:
        return "amd"
    return "primary"


def node_label(node: str | None = None) -> str:
    n = (node or local_node()).lower()
    return "AMD .5" if n in ("amd", "backup", "5", ".5") else "Intel .4"


def any_whatsapp_connected() -> bool:
    return connection_open(node="primary") or connection_open(node="amd")


def send_alert_whatsapp(text: str, number: str | None = None, *, prefix_node: bool = True) -> dict[str, Any]:
    """Alerta operativa → SIEMPRE al número personal (RALFIA_ALERTS_TO / NOTIFY_WHATSAPP_TO).

    RALFIA_ALERTS_VIA_NODE=primary (default): envía vía Evolution Intel (PC Doctor)
    con failover a AMD si Intel falla.
    """
    alerts_via = (os.getenv("RALFIA_ALERTS_VIA_NODE") or "primary").strip().lower()
    dest = (number or os.getenv("RALFIA_ALERTS_TO") or NOTIFY_WHATSAPP_TO or "").strip()
    local = local_node()
    body = text.strip()
    via_node = "primary" if alerts_via in ("primary", "intel", "4", ".4") else "amd"
    if prefix_node and body and "— vía " not in body.lower() and "— nodo " not in body.lower():
        origin_note = ""
        if local != via_node:
            origin_note = f" · tarea en {node_label(local)}"
        body = f"{body.rstrip()}\n— vía {node_label(via_node)}{origin_note}"

    if alerts_via in ("primary", "intel", "4", ".4"):
        result = send_whatsapp(body, number=dest, node="primary")
        if result.get("ok"):
            result["via_node"] = "primary"
            result["origin_node"] = local
            result["alert_policy"] = "RALFIA_ALERTS_VIA_NODE=primary"
            return result
        if WHATSAPP_AMD_SEND_ENABLED:
            second = send_whatsapp(body, number=dest, node="amd")
            second["failover_from"] = "primary"
            if second.get("ok"):
                second["via_node"] = "amd"
                second["origin_node"] = local
            return second
        return result

    # Legacy: nodo local primero (solo si override explícito)
    remote = "primary" if local == "amd" else "amd"
    first = send_whatsapp(body, number=dest, node=local)
    if first.get("ok"):
        first["via_node"] = local
        first["origin_node"] = local
        return first
    second = send_whatsapp(body, number=dest, node=remote)
    second["failover_from"] = local
    if second.get("ok"):
        second["via_node"] = remote
        second["origin_node"] = local
    return second


def _node_config(node: str | None = None) -> tuple[str, str]:
    """Resuelve (base_url, instance) según nodo: primary | amd."""
    n = (node or EVOLUTION_DEFAULT_NODE or "primary").strip().lower()
    if n in ("amd", "backup", "5", ".5"):
        return EVOLUTION_AMD_BASE_URL, EVOLUTION_AMD_INSTANCE
    return EVOLUTION_BASE_URL, EVOLUTION_INSTANCE


def _headers() -> dict[str, str]:
    return {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}


def _resolved_node(node: str | None) -> str:
    return (node or EVOLUTION_DEFAULT_NODE or "primary").strip().lower()


def _amd_send_blocked(node: str | None, *, kind: str = "message") -> dict[str, Any] | None:
    """Bloquea envíos AMD durante warm-up del chip o si status está desactivado."""
    n = _resolved_node(node)
    if n not in ("amd", "backup", "5", ".5"):
        return None
    if kind == "status":
        if not WHATSAPP_STATUS_ENABLED or not WHATSAPP_AMD_STATUS_ENABLED:
            return {
                "ok": False,
                "status": "blocked",
                "message": "Envío de estados WhatsApp desactivado en nodo AMD (WHATSAPP_AMD_STATUS_ENABLED=0)",
                "hint": "Usa node=primary o activa flags tras warm-up del chip nuevo.",
            }
        return None
    if not WHATSAPP_AMD_SEND_ENABLED:
        return {
            "ok": False,
            "status": "blocked",
            "message": "Envíos WhatsApp desactivados en nodo AMD (WHATSAPP_AMD_SEND_ENABLED=0)",
            "hint": "Usa node=primary o activa tras estabilizar el chip nuevo.",
        }
    return None


def evolution_available(node: str | None = None) -> bool:
    base, _ = _node_config(node)
    if not base:
        return False
    try:
        r = httpx.get(f"{base}/", timeout=5.0)
        return r.status_code < 500
    except Exception:
        return False


def dual_whatsapp_status() -> dict[str, Any]:
    """Estado de ambas líneas (números distintos)."""
    out: dict[str, Any] = {}
    for node in ("primary", "amd"):
        base, inst = _node_config(node)
        out[node] = {
            "base_url": base,
            "instance": inst,
            "api_up": evolution_available(node),
            "connected": connection_open(instance=inst, node=node),
        }
    return out


def connection_open(instance: str | None = None, *, node: str | None = None) -> bool:
    base, default_inst = _node_config(node)
    name = instance or default_inst
    if not name or not EVOLUTION_API_KEY:
        return False
    try:
        r = httpx.get(
            f"{base}/instance/connectionState/{name}",
            headers=_headers(),
            timeout=10.0,
        )
        if not r.is_success:
            return False
        body = r.json()
        if isinstance(body, dict):
            inst = body.get("instance") or body
            state = inst.get("state") or inst.get("connectionStatus") or ""
            return state == "open"
    except Exception:
        return False
    return False


def get_media_base64(payload: dict[str, Any], *, node: str | None = None) -> str:
    """Retrieve inbound media without exposing Evolution credentials to callers or logs."""
    base, inst = _node_config(node)
    data = payload.get("data") or {}
    if isinstance(data, list):
        data = data[0] if data else {}
    key = data.get("key") if isinstance(data, dict) else None
    if not EVOLUTION_API_KEY or not inst or not isinstance(key, dict) or not key.get("id"):
        raise RuntimeError("evolution_media_request_not_configured")
    response = httpx.post(
        f"{base}/chat/getBase64FromMediaMessage/{inst}",
        headers=_headers(),
        json={"message": {"key": key}},
        timeout=30.0,
    )
    response.raise_for_status()
    body = response.json()
    encoded = body.get("base64") or (body.get("data") or {}).get("base64")
    if not isinstance(encoded, str) or not encoded:
        raise RuntimeError("evolution_media_base64_missing")
    return encoded


def _normalize_destination(dest: str) -> tuple[str | None, str | None]:
    raw = (dest or "").strip()
    if not raw:
        return None, None
    if "@" in raw:
        return raw, raw
    digits = "".join(c for c in raw if c.isdigit())
    if digits:
        return digits, digits
    return None, None


def send_whatsapp(text: str, number: str | None = None, *, instance: str | None = None, node: str | None = None) -> dict[str, Any]:
    blocked = _amd_send_blocked(node, kind="message")
    if blocked:
        return blocked
    dest = (number or NOTIFY_WHATSAPP_TO or "").strip()
    base, default_inst = _node_config(node)
    inst = instance or default_inst
    if not dest:
        return {"ok": False, "status": "error", "message": "NOTIFY_WHATSAPP_TO vacío"}
    if not EVOLUTION_API_KEY or not inst:
        return {"ok": False, "status": "error", "message": "Evolution no configurado en .env"}
    target, normalized = _normalize_destination(dest)
    if not target:
        return {"ok": False, "status": "error", "message": "número o groupJid inválido"}

    url = f"{base}/message/sendText/{inst}"
    try:
        r = httpx.post(
            url,
            headers=_headers(),
            json={"number": target, "text": text[:4000], "delay": 800},
            timeout=25.0,
        )
        ok = r.status_code in (200, 201)
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:300]}
        result = {
            "ok": ok,
            "status": "sent" if ok else "error",
            "http_status": r.status_code,
            "response": body,
            "number": normalized or target,
            "node": (node or EVOLUTION_DEFAULT_NODE or "primary"),
            "instance": inst,
        }
        try:
            from raphiia_openai import whatsapp_message_ledger

            result["ledger"] = whatsapp_message_ledger.record_outbound(
                text=text[:4000],
                target=normalized or target,
                node=str(node or EVOLUTION_DEFAULT_NODE or "primary"),
                instance=inst,
                response=body,
                ok=ok,
            )
        except Exception:
            result["ledger"] = {"ok": False, "error": "ledger_unavailable"}
        return result
    except Exception as exc:
        return {"ok": False, "status": "error", "message": str(exc)}


def send_whatsapp_interactive(
    text: str,
    buttons: list[dict[str, str]],
    number: str | None = None,
    *,
    footer: str = "RalfIA · operación segura",
    fallback_text: str | None = None,
    instance: str | None = None,
    node: str | None = None,
) -> dict[str, Any]:
    """Envía botones reply allowlisted y una copia textual siempre visible."""
    import re

    dest = (number or NOTIFY_WHATSAPP_TO or "").strip()
    base, default_inst = _node_config(node)
    inst = instance or default_inst
    target, normalized = _normalize_destination(dest)
    if not target or not EVOLUTION_API_KEY or not inst:
        return send_whatsapp(fallback_text or text, number=number, instance=instance, node=node)
    clean: list[dict[str, str]] = []
    for item in buttons[:3]:
        action_id = str(item.get("id") or "").strip()
        label = str(item.get("label") or "").strip()[:24]
        if not label or not re.fullmatch(
            r"(?:maint\.(?:confirm|cancel)\.[A-Za-z0-9_-]{4,100}|"
            r"menu\.(?:status|email|more|services|notifications|custom))",
            action_id,
        ):
            continue
        clean.append({"type": "reply", "displayText": label, "id": action_id})
    if not clean:
        return send_whatsapp(fallback_text or text, number=number, instance=instance, node=node)
    is_menu = all(str(item.get("id") or "").startswith("menu.") for item in clean)
    try:
        response = httpx.post(
            f"{base}/message/sendButtons/{inst}",
            headers=_headers(),
            json={
                "number": target,
                "title": "RalfIA · menú" if is_menu else "Confirmación requerida",
                "description": text[:900],
                "footer": footer[:80],
                "buttons": clean,
                "delay": 800,
            },
            timeout=25.0,
        )
        try:
            body = response.json()
        except Exception:
            body = {"raw": response.text[:300]}
        if response.status_code in (200, 201):
            result = {
                "ok": True,
                "status": "sent",
                "interactive": True,
                "http_status": response.status_code,
                "response": body,
                "number": normalized or target,
                "node": str(node or EVOLUTION_DEFAULT_NODE or "primary"),
                "instance": inst,
            }
            try:
                from raphiia_openai import whatsapp_message_ledger

                result["ledger"] = whatsapp_message_ledger.record_outbound(
                    text=text[:900],
                    target=normalized or target,
                    node=result["node"],
                    instance=inst,
                    response=body,
                    ok=True,
                )
            except Exception:
                result["ledger"] = {"ok": False, "error": "ledger_unavailable"}
            # Some Evolution/WhatsApp combinations acknowledge sendButtons with
            # HTTP 200 but never render the interactive message on the phone.
            # Always send the same challenge as plain text too: confirmation is
            # still scoped to the owner/chat and the one-time code, so this does
            # not weaken authorization.
            text_result = send_whatsapp(
                fallback_text or text,
                number=number,
                instance=instance,
                node=node,
            )
            result["text_fallback"] = text_result
            result["delivery_mode"] = "interactive_plus_text"
            result["ok"] = bool(result["ok"] or text_result.get("ok"))
            return result
    except Exception:
        pass
    fallback = fallback_text or text
    result = send_whatsapp(fallback, number=number, instance=instance, node=node)
    result["interactive"] = False
    result["fallback"] = "numbered_text"
    return result


def send_whatsapp_status(
    content: str = "",
    *,
    status_type: str = "text",
    caption: str = "",
    file_path: str | None = None,
    all_contacts: bool = False,
    status_jid_list: list[str] | None = None,
    background_color: str = "#008000",
    font: int = 1,
    node: str | None = None,
) -> dict[str, Any]:
    """Publica un estado/story en WhatsApp vía Evolution sendStatus.

    Basado en el payload documentado por Evolution API: type/content/caption/backgroundColor/font/allContacts/statusJidList.
    """
    from pathlib import Path

    if not WHATSAPP_STATUS_ENABLED:
        return {
            "ok": False,
            "status": "blocked",
            "message": "Envío de estados WhatsApp desactivado globalmente (WHATSAPP_STATUS_ENABLED=0)",
            "hint": "Activa el flag tras warm-up del chip o usa otro destino de publicación.",
        }
    blocked = _amd_send_blocked(node, kind="status")
    if blocked:
        return blocked
    base, inst = _node_config(node)
    if not EVOLUTION_API_KEY or not inst:
        return {"ok": False, "status": "error", "message": "Evolution no configurado en .env"}
    clean_jids = [str(x).strip() for x in (status_jid_list or []) if str(x).strip()]
    if all_contacts and not clean_jids:
        return {
            "ok": False,
            "status": "error",
            "message": "all_contacts=true requiere status_jid_list en esta versión para evitar el bug de sendStatus",
            "hint": "Usa status_jid_list con los JID destinatarios o actualiza Evolution API antes de activar all_contacts.",
        }

    url = f"{base}/message/sendStatus/{inst}"
    status_kind = (status_type or "text").strip().lower()

    def _status_jids(jids: list[str]) -> list[str]:
        out: list[str] = []
        for jid in jids:
            raw = str(jid).strip()
            if not raw:
                continue
            digits = "".join(c for c in raw.split("@", 1)[0] if c.isdigit())
            out.append(digits or raw)
        return out

    jid_targets = _status_jids(clean_jids)
    try:
        if file_path:
            import base64
            import mimetypes

            path_obj = Path(file_path)
            if not path_obj.is_file():
                return {"ok": False, "status": "error", "message": f"archivo no encontrado: {path_obj}"}
            mime = mimetypes.guess_type(path_obj.name)[0] or "application/octet-stream"
            encoded = base64.b64encode(path_obj.read_bytes()).decode("ascii")
            payload = {
                "type": status_kind if status_kind != "text" else "image",
                "content": f"data:{mime};base64,{encoded}",
                "caption": (caption or "")[:900],
                "allContacts": bool(all_contacts),
                "backgroundColor": background_color,
                "font": int(font or 1),
            }
            if jid_targets:
                payload["statusJidList"] = jid_targets
            r = httpx.post(url, headers=_headers(), json=payload, timeout=120.0)
            payload = {"payload": payload, "file_path": str(path_obj)}
        else:
            if not content.strip():
                return {"ok": False, "status": "error", "message": "content vacío"}
            payload = {
                "type": status_kind,
                "content": content.strip(),
                "caption": (caption or "")[:900],
                "backgroundColor": background_color,
                "font": int(font or 1),
                "allContacts": bool(all_contacts),
            }
            if jid_targets:
                payload["statusJidList"] = jid_targets
            r = httpx.post(url, headers=_headers(), json=payload, timeout=60.0)
        ok = r.status_code in (200, 201)
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:300]}
        return {
            "ok": ok,
            "status": "sent" if ok else "error",
            "http_status": r.status_code,
            "response": body,
            "payload": payload,
            "node": (node or EVOLUTION_DEFAULT_NODE or "primary"),
            "instance": inst,
        }
    except Exception as exc:
        return {"ok": False, "status": "error", "message": str(exc), "payload": {"file_path": file_path, "content": content, "status_type": status_type}}


def send_whatsapp_audio(
    text: str,
    number: str | None = None,
    *,
    instance: str | None = None,
    node: str | None = None,
    voice: str | None = None,
) -> dict[str, Any]:
    """Sintetiza TTS (Piper/XTTS) y envía nota de voz por Evolution sendMedia."""
    import base64
    import subprocess
    import tempfile
    from pathlib import Path

    blocked = _amd_send_blocked(node, kind="message")
    if blocked:
        return blocked
    dest = (number or NOTIFY_WHATSAPP_TO or "").strip()
    base, default_inst = _node_config(node)
    inst = instance or default_inst
    if not dest or not EVOLUTION_API_KEY or not inst:
        return {"ok": False, "status": "error", "message": "destino o Evolution no configurado"}
    target, normalized = _normalize_destination(dest)
    if not target:
        return {"ok": False, "status": "error", "message": "número o groupJid inválido"}

    from raphiia_openai.voice_gateway import _synthesize_reply

    with tempfile.TemporaryDirectory(prefix="ralfia-wa-audio-") as tmpdir:
        wav_path, err = _synthesize_reply(text[:2000], voice=voice)
        if not wav_path or not Path(wav_path).is_file():
            return {"ok": False, "status": "error", "message": err or "tts_failed"}
        src = Path(wav_path)
        ogg = Path(tmpdir) / "reply.ogg"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(src), "-c:a", "libopus", "-b:a", "48k", str(ogg)],
                capture_output=True,
                timeout=45,
                check=True,
            )
            send_path, mime = ogg, "audio/ogg; codecs=opus"
        except Exception:
            send_path, mime = src, "audio/wav"

        raw = send_path.read_bytes()
        if len(raw) > 12_000_000:
            return {"ok": False, "status": "error", "message": "audio demasiado grande"}

        url = f"{base}/message/sendMedia/{inst}"
        try:
            r = httpx.post(
                url,
                headers=_headers(),
                json={
                    "number": target,
                    "mediatype": "audio",
                    "mimetype": mime,
                    "fileName": send_path.name,
                    "media": base64.b64encode(raw).decode("ascii"),
                    "ptt": True,
                    "delay": 800,
                },
                timeout=90.0,
            )
            ok = r.status_code in (200, 201)
            try:
                body = r.json()
            except Exception:
                body = {"raw": r.text[:300]}
            return {
                "ok": ok,
                "status": "sent" if ok else "error",
                "http_status": r.status_code,
                "response": body,
                "number": normalized or target,
                "node": (node or EVOLUTION_DEFAULT_NODE or "primary"),
                "instance": inst,
                "mediatype": "audio",
            }
        except Exception as exc:
            return {"ok": False, "status": "error", "message": str(exc)}


def send_whatsapp_document(
    file_path: str,
    number: str | None = None,
    *,
    caption: str = "",
    file_name: str | None = None,
    mimetype: str | None = None,
    instance: str | None = None,
    node: str | None = None,
) -> dict[str, Any]:
    """Envía documento (PDF, etc.) por Evolution sendMedia."""
    import base64
    from pathlib import Path

    dest = (number or NOTIFY_WHATSAPP_TO or "").strip()
    base, default_inst = _node_config(node)
    inst = instance or default_inst
    path = Path(file_path)
    if not path.is_file():
        return {"ok": False, "status": "error", "message": f"archivo no encontrado: {path}"}
    if not dest or not EVOLUTION_API_KEY or not inst:
        return {"ok": False, "status": "error", "message": "destino o Evolution no configurado"}
    target, normalized = _normalize_destination(dest)
    if not target:
        return {"ok": False, "status": "error", "message": "número o groupJid inválido"}
    raw = path.read_bytes()
    if len(raw) > 15_000_000:
        return {"ok": False, "status": "error", "message": "archivo demasiado grande"}
    mime = mimetype or "application/pdf"
    fname = file_name or path.name
    url = f"{base}/message/sendMedia/{inst}"
    try:
        r = httpx.post(
            url,
            headers=_headers(),
            json={
                "number": target,
                "mediatype": "document",
                "mimetype": mime,
                "fileName": fname,
                "caption": (caption or "")[:900],
                "media": base64.b64encode(raw).decode("ascii"),
                "delay": 800,
            },
            timeout=60.0,
        )
        ok = r.status_code in (200, 201)
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:300]}
        return {
            "ok": ok,
            "status": "sent" if ok else "error",
            "http_status": r.status_code,
            "response": body,
            "number": normalized or target,
            "file": str(path),
            "node": (node or EVOLUTION_DEFAULT_NODE or "primary"),
        }
    except Exception as exc:
        return {"ok": False, "status": "error", "message": str(exc)}
