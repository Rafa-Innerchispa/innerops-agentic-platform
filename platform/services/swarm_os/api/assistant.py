"""Asistente Centro de Datos — chat libre + acciones ERP + búsqueda web."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Header, UploadFile
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1", tags=["assistant"])

_SYSTEM = """Eres Ralphi IA v2.0, asistente del Centro de Datos de PC Doctor (Ecuador).

Puedes:
• Conversar libremente en español, con tono profesional y cercano.
• Explicar tus capacidades: ERP local (clientes, visitas, informes, inventario, catálogo, cotizaciones), voz Whisper, Ollama local, búsqueda web, subida de archivos.
• Los datos de negocio se guardan en MongoDB solo cuando están completos y validados (sin duplicados de RUC).
• El chat se guarda por sesiones — no se borra solo; el usuario puede exportar respaldo JSON.
• Búsqueda web: si recibes resultados web, cítalos y di de dónde vienen; si no hay datos, dilo con honestidad.
• No inventes RUC, teléfonos ni precios de productos si no los tienes.

Comandos estructurados (además del chat): listar clientes, buscar catálogo, crear cliente/proveedor/producto/cotización/visita, estadísticas, ayuda."""

_WEB_HINT = re.compile(
    r"internet|en\s+l[ií]nea|online|web|busca(r)?\s+(en\s+)?(google|internet|la\s+red)|"
    r"datasheet|ficha\s+t[eé]cnica|especificaciones|manual\s+de|modelo\s+de|"
    r"precio\s+(de|del)|empresa\s+\w+|marca\s+\w+|c[aá]mara\s+\w+",
    re.I,
)


class ChatIn(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str | None = None


def _db():
    from tools.mongo import get_db

    return get_db()


def _session_history(session_id: str | None, user: str, limit: int = 16) -> list[dict[str, str]]:
    if not session_id:
        return []
    db = _db()
    msgs = list(
        db.chat_messages.find({"session_id": session_id, "username": user}, {"_id": 0, "role": 1, "text": 1})
        .sort("created_at", -1)
        .limit(limit)
    )
    msgs.reverse()
    out = []
    for m in msgs:
        role = m.get("role", "user")
        if role not in ("user", "assistant"):
            continue
        out.append({"role": role, "content": m.get("text", "")[:4000]})
    return out


def _help_text() -> str:
    return """Puedo ayudarte de varias formas:

💬 Chat libre — pregúntame lo que quieras (también sobre mis capacidades).
🌐 Búsqueda web — datasheets, modelos de cámara, empresas, fichas técnicas.
📎 Archivos — sube PDF, imágenes o texto; los guardo en el servidor y los leo.
📋 ERP local — clientes, visitas, informes, catálogo, inventario, cotizaciones.

Comandos rápidos:
• listar clientes / estadísticas
• buscar catálogo CCTV
• crear cliente / proveedor / producto / cotización / visita

Los registros en base de datos solo se crean con datos completos y sin duplicados.
Tus conversaciones se guardan por sesión (panel izquierdo) y puedes exportar respaldo JSON."""


def _parse_create_product(text: str) -> dict[str, Any] | None:
    m = re.search(
        r"crear\s+(?:producto|servicio|cat[aá]logo)\s+(?:c[oó]digo\s+)?(\S+)\s+nombre\s+(.+?)(?:\s+precio\s+([\d.]+))?$",
        text,
        re.I,
    )
    if not m:
        return None
    return {"code": m.group(1), "nombre": m.group(2).strip(), "precio_sugerido": float(m.group(3) or 0)}


def _try_crud(msg: str, low: str) -> dict[str, Any] | None:
    from api.crud_v1 import (
        CatalogIn,
        ClientIn,
        QuoteIn,
        SupplierIn,
        VisitIn,
        admin_stats,
        create_catalog,
        create_client,
        create_quote,
        create_supplier,
        create_visit,
    )

    db = _db()

    if "estadística" in low or low == "stats":
        s = admin_stats()
        return {"reply": f"Registros en el sistema:\n{s}", "data": s}

    if "listar cliente" in low or "cuántos cliente" in low or "cuantos cliente" in low:
        n = db.clients.count_documents({})
        sample = list(db.clients.find({}, {"_id": 0, "name": 1, "client_id": 1, "ruc": 1}).limit(5))
        lines = [f"• {c['name']} — RUC {c.get('ruc', '—')}" for c in sample]
        return {"reply": f"Hay {n} clientes en MongoDB. Algunos:\n" + "\n".join(lines), "data": sample}

    if "buscar catálogo" in low or "buscar catalogo" in low or "listar catálogo" in low or "listar catalogo" in low:
        q = re.sub(r".*cat[aá]logo\s*", "", low, flags=re.I).strip() or "."
        filt = (
            {"$or": [
                {"nombre": {"$regex": q, "$options": "i"}},
                {"code": {"$regex": q, "$options": "i"}},
            ]}
            if q != "."
            else {}
        )
        items = list(
            db.catalog_products.find(filt, {"_id": 0, "code": 1, "nombre": 1, "precio_sugerido": 1}).limit(8)
        )
        if not items:
            return {"reply": f"No encontré nada en catálogo local para «{q}»."}
        lines = [f"• {i['code']} — {i.get('nombre', '')} (${i.get('precio_sugerido', 0)})" for i in items]
        return {"reply": "Catálogo local:\n" + "\n".join(lines), "data": items}

    m = re.search(r"crear\s+cliente\s+(?:ruc\s+(\d+)\s+)?(?:nombre\s+)?(.+)", msg, re.I)
    if m:
        ruc = m.group(1) or "9999999999001"
        name = (m.group(2) or "").strip()
        doc = create_client(ClientIn(ruc=ruc, name=name, estado="Cliente"))
        return {"reply": f"✅ Cliente guardado en MongoDB: {doc['name']} — RUC {doc.get('ruc')}", "data": doc}

    m = re.search(r"crear\s+proveedor\s+(.+)", msg, re.I)
    if m:
        doc = create_supplier(SupplierIn(nombre=m.group(1).strip()))
        return {"reply": f"✅ Proveedor creado: {doc['nombre']}", "data": doc}

    prod = _parse_create_product(low)
    if prod:
        doc = create_catalog(CatalogIn(**prod))
        return {"reply": f"✅ Producto en catálogo: {doc['code']} — {doc['nombre']}", "data": doc}

    m = re.search(r"crear\s+cotizaci[oó]n\s+cliente\s+(\S+)", low)
    if m:
        doc = create_quote(QuoteIn(client_id=m.group(1)))
        return {"reply": f"✅ Cotización {doc.get('serial', '')} creada", "data": doc}

    m = re.search(r"crear\s+visita\s+cliente\s+(\S+)", low)
    if m:
        doc = create_visit(VisitIn(client_id=m.group(1), notas=msg))
        return {"reply": f"✅ Visita creada — {doc['visit_id']}", "data": doc}

    if re.search(r"crear\s+informe", low):
        return {
            "reply": "Para informes: menú Informes técnicos → busca cliente → elige visita → se genera número automático.",
        }
    return None


def _capabilities_reply(low: str) -> str | None:
    hints = (
        "qué puedes", "que puedes", "qué sabes", "que sabes", "tus capacidades",
        "para qué sirves", "para que sirves", "quién eres", "quien eres", "qué eres",
        "que eres", "cómo funcionas", "como funcionas",
    )
    if any(h in low for h in hints):
        return _help_text()
    return None


@router.post("/assistant/chat")
def assistant_chat(body: ChatIn, authorization: str | None = Header(None)):
    from api.chat_store import _user_from_token

    msg = body.message.strip()
    low = msg.lower()
    user = _user_from_token(authorization)

    if low in {"ayuda", "help", "?"}:
        return {"reply": _help_text(), "source": "help"}

    cap = _capabilities_reply(low)
    if cap:
        return {"reply": cap, "source": "capabilities"}

    crud = _try_crud(msg, low)
    if crud:
        crud["source"] = "crud"
        return crud

    web_block = ""
    used_web = False
    if _WEB_HINT.search(msg):
        from tools.web_search import format_search_context, search_web

        results = search_web(msg, max_results=5)
        if results:
            web_block = "\n\n[Resultados web DuckDuckGo]\n" + format_search_context(results)
            used_web = True

    from tools.ollama_chat import ollama_available, ollama_chat

    if not ollama_available():
        base = "Ollama no está disponible en este momento."
        if web_block:
            return {"reply": base + web_block, "source": "web_only"}
        return {"reply": base + " Escribe «ayuda» para comandos del ERP.", "source": "offline"}

    history = _session_history(body.session_id, user)
    messages: list[dict[str, str]] = [{"role": "system", "content": _SYSTEM}]
    messages.extend(history[-14:])
    user_content = msg + web_block if web_block else msg
    if messages and messages[-1].get("role") == "user" and messages[-1].get("content", "").startswith(msg):
        if web_block:
            messages[-1] = {"role": "user", "content": user_content}
    else:
        messages.append({"role": "user", "content": user_content})

    try:
        ai = ollama_chat(messages, temperature=0.65, timeout=180)
        source = "ollama+web" if used_web else "ollama"
        return {"reply": ai.strip(), "source": source, "web_search": used_web}
    except Exception as e:
        if web_block:
            return {"reply": f"No pude usar Ollama ({e}). Resultados web:\n{web_block}", "source": "web_only"}
        return {"reply": f"Error con Ollama: {e}. Escribe «ayuda».", "source": "error"}


@router.post("/voice/transcribe")
async def voice_transcribe(audio_file: UploadFile = File(...)):
    from tools.transcribe import transcribe_audio_file

    content = await audio_file.read()
    suffix = Path(audio_file.filename or "audio.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        path = tmp.name
    try:
        return transcribe_audio_file(path)
    finally:
        Path(path).unlink(missing_ok=True)
