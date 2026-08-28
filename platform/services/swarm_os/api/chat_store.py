"""Sesiones de chat del Centro de Datos — persistencia completa por usuario."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, File, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from tools.schema import new_id

router = APIRouter(prefix="/api/v1", tags=["chat"])


def _db():
    from tools.mongo import get_db

    return get_db()


def _now():
    return datetime.now(timezone.utc)


def _user_from_token(authorization: str | None) -> str:
    from api.auth_users import get_session_user

    if not authorization or not authorization.startswith("Bearer "):
        return "anon"
    token = authorization[7:].strip()
    user = get_session_user(_db(), token)
    return user["username"] if user else "anon"


def _session_title_from_text(text: str) -> str:
    t = text.strip().replace("\n", " ")
    return (t[:48] + "…") if len(t) > 48 else (t or "Nueva conversación")


class SessionCreate(BaseModel):
    title: str = "Nueva conversación"


class SessionRename(BaseModel):
    title: str = Field(..., min_length=1)


class ChatAppend(BaseModel):
    role: str
    text: str = Field(..., min_length=1)
    session_id: str | None = None


def _get_session(db, user: str, session_id: str) -> dict:
    doc = db.chat_sessions.find_one({"session_id": session_id, "username": user}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "sesión no encontrada")
    return doc


def _ensure_session(db, user: str, session_id: str | None) -> str:
    if session_id:
        _get_session(db, user, session_id)
        return session_id
    existing = db.chat_sessions.find_one({"username": user}, sort=[("updated_at", -1)])
    if existing:
        return existing["session_id"]
    sid = new_id("cse")
    now = _now()
    db.chat_sessions.insert_one({
        "session_id": sid,
        "username": user,
        "title": "Nueva conversación",
        "created_at": now,
        "updated_at": now,
        "message_count": 0,
    })
    db.chat_messages.update_many(
        {"username": user, "session_id": {"$exists": False}},
        {"$set": {"session_id": sid}},
    )
    return sid


@router.get("/chat/sessions")
def list_sessions(authorization: str | None = Header(None)):
    user = _user_from_token(authorization)
    db = _db()
    _ensure_session(db, user, None)
    data = list(
        db.chat_sessions.find({"username": user}, {"_id": 0})
        .sort("updated_at", -1)
        .limit(100)
    )
    return {"username": user, "sessions": data}


@router.post("/chat/sessions")
def create_session(body: SessionCreate, authorization: str | None = Header(None)):
    user = _user_from_token(authorization)
    db = _db()
    sid = new_id("cse")
    now = _now()
    doc = {
        "session_id": sid,
        "username": user,
        "title": body.title or "Nueva conversación",
        "created_at": now,
        "updated_at": now,
        "message_count": 0,
    }
    db.chat_sessions.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/chat/sessions/{session_id}")
def rename_session(session_id: str, body: SessionRename, authorization: str | None = Header(None)):
    user = _user_from_token(authorization)
    db = _db()
    _get_session(db, user, session_id)
    db.chat_sessions.update_one(
        {"session_id": session_id},
        {"$set": {"title": body.title, "updated_at": _now()}},
    )
    return {"session_id": session_id, "title": body.title}


@router.delete("/chat/sessions/{session_id}")
def delete_session(session_id: str, authorization: str | None = Header(None)):
    user = _user_from_token(authorization)
    db = _db()
    _get_session(db, user, session_id)
    db.chat_messages.delete_many({"session_id": session_id, "username": user})
    db.chat_sessions.delete_one({"session_id": session_id})
    return {"deleted": session_id}


@router.get("/chat/history")
def chat_history(
    authorization: str | None = Header(None),
    session_id: str | None = None,
    limit: int = 500,
):
    user = _user_from_token(authorization)
    db = _db()
    sid = _ensure_session(db, user, session_id)
    msgs = list(
        db.chat_messages.find({"username": user, "session_id": sid}, {"_id": 0})
        .sort("created_at", 1)
        .limit(min(limit, 2000))
    )
    return {"username": user, "session_id": sid, "messages": msgs}


@router.post("/chat/append")
def chat_append(body: ChatAppend, authorization: str | None = Header(None)):
    user = _user_from_token(authorization)
    db = _db()
    sid = _ensure_session(db, user, body.session_id)
    now = _now()
    doc = {
        "session_id": sid,
        "username": user,
        "role": body.role,
        "text": body.text,
        "created_at": now,
    }
    db.chat_messages.insert_one(doc)
    set_fields: dict[str, Any] = {"updated_at": now}
    sess = db.chat_sessions.find_one({"session_id": sid})
    if sess and sess.get("message_count", 0) == 0 and body.role == "user":
        set_fields["title"] = _session_title_from_text(body.text)
    db.chat_sessions.update_one(
        {"session_id": sid},
        {"$set": set_fields, "$inc": {"message_count": 1}},
    )
    doc.pop("_id", None)
    return doc


@router.delete("/chat/history")
def chat_clear(authorization: str | None = Header(None), session_id: str | None = None):
    user = _user_from_token(authorization)
    db = _db()
    if session_id:
        _get_session(db, user, session_id)
        db.chat_messages.delete_many({"session_id": session_id, "username": user})
        db.chat_sessions.update_one({"session_id": session_id}, {"$set": {"message_count": 0, "updated_at": _now()}})
        return {"cleared": session_id}
    db.chat_messages.delete_many({"username": user})
    db.chat_sessions.delete_many({"username": user})
    return {"cleared": user}


@router.get("/chat/sessions/{session_id}/export")
def export_session(session_id: str, authorization: str | None = Header(None)):
    user = _user_from_token(authorization)
    db = _db()
    sess = _get_session(db, user, session_id)
    msgs = list(
        db.chat_messages.find({"session_id": session_id}, {"_id": 0}).sort("created_at", 1)
    )
    files = list(db.chat_files.find({"session_id": session_id}, {"_id": 0}))
    payload = {
        "exported_at": _now().isoformat(),
        "username": user,
        "session": sess,
        "messages": msgs,
        "files": files,
    }
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="ralphi-chat-{session_id}.json"'},
    )


@router.post("/chat/sessions/{session_id}/upload")
async def upload_to_session(
    session_id: str,
    file: UploadFile = File(...),
    authorization: str | None = Header(None),
):
    from tools.chat_uploads import save_chat_file
    from tools.file_reader import read_file

    user = _user_from_token(authorization)
    db = _db()
    _get_session(db, user, session_id)
    content = await file.read()
    if not content:
        raise HTTPException(400, "archivo vacío")
    entry = save_chat_file(session_id, file.filename or "archivo.bin", content)
    summary = ""
    try:
        extracted = read_file(entry["path"])
        summary = (extracted.get("text") or "")[:8000]
    except Exception as e:
        summary = f"No se pudo leer el contenido: {e}"

    meta = {**entry, "username": user, "summary_preview": summary[:500]}
    db.chat_files.insert_one(meta)
    meta.pop("_id", None)

    note = (
        f"📎 Archivo guardado: {entry['filename']} ({entry['size']} bytes)\n"
        f"Ruta servidor: {entry['path']}\n"
    )
    if summary:
        note += f"\nContenido extraído (resumen):\n{summary[:2000]}"
        if len(summary) > 2000:
            note += "\n… (recortado; el archivo completo está en disco)"

    now = _now()
    db.chat_messages.insert_one({
        "session_id": session_id,
        "username": user,
        "role": "assistant",
        "text": note,
        "attachment": entry["file_id"],
        "created_at": now,
    })
    db.chat_sessions.update_one(
        {"session_id": session_id},
        {"$set": {"updated_at": now}, "$inc": {"message_count": 1}},
    )
    return {"file": meta, "preview": note}
