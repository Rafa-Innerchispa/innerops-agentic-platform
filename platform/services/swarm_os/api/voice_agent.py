"""Voz → Whisper → Ollama: extraer campos, validar, confirmar antes de crear."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1", tags=["voice-agent"])

CLIENT_SCHEMA = """
Extrae datos de cliente Ecuador. Responde SOLO JSON:
{
  "intent": "create_client|search|unknown",
  "ruc": "",
  "name": "",
  "phone": "",
  "email": "",
  "city": "",
  "pais": "Ecuador",
  "estado": "Cliente",
  "missing_fields": [],
  "confidence": 0.0,
  "clarification": "pregunta al usuario si falta algo"
}
Reglas: ruc 10 o 13 dígitos; phone formato +5939xxxxxxxx; si falta dato crítico (ruc, name) ponlo en missing_fields.
"""


class VoiceTextIn(BaseModel):
    text: str = Field(..., min_length=2)
    confirm: bool = False


def _db():
    from tools.mongo import get_db

    return get_db()


_GREETING = re.compile(
    r"^\s*(hola|buenas|buenos\s+d[ií]as|buenas\s+tardes|buenas\s+noches|qu[eé]\s+tal|hey|saludos)\s*[!?.…]*\s*$",
    re.I,
)
_CREATE_HINT = re.compile(r"crear|nuevo\s+cliente|cliente\s+nuevo|ruc|c[eé]dula|tel[eé]fono|registrar", re.I)


def _friendly_menu() -> str:
    return (
        "¿En qué puedo ayudarte?\n\n"
        "• Crear cliente (di RUC, nombre y teléfono)\n"
        "• Usa los botones de acceso rápido arriba del chat\n"
        "• Menú lateral: visitas, informes, inventario, catálogo\n"
        "• Escribe «ayuda» para ver comandos"
    )


def _process_voice_text(text: str, confirm: bool = False) -> dict[str, Any]:
    from api.validators import normalize_phone_ec, validate_email, validate_phone_ec, validate_ruc_cedula
    from tools.gates import check_duplicate_client
    from tools.ollama_chat import ollama_available, ollama_chat

    transcript = text.strip()
    extracted: dict[str, Any] = {"intent": "unknown"}

    if _GREETING.match(transcript):
        return {
            "transcript": transcript,
            "extracted": {"intent": "greeting"},
            "ready": False,
            "reply": f"Hola — ¿cómo estás? Soy Ralphi IA v2.0, tu asistente en el Centro de Datos.\n\n{_friendly_menu()}",
        }

    if not confirm and not _CREATE_HINT.search(transcript):
        return {
            "transcript": transcript,
            "extracted": {"intent": "chat"},
            "ready": False,
            "reply": _friendly_menu(),
        }

    reply_parts = [f"Escuché: «{transcript}»"]

    if ollama_available():
        try:
            raw = ollama_chat(
                [
                    {"role": "system", "content": CLIENT_SCHEMA},
                    {"role": "user", "content": transcript},
                ],
                format_json=True,
            )
            extracted = json.loads(raw)
            reply_parts.append("(Ollama estructuró los datos del cliente)")
        except Exception as e:
            reply_parts.append(f"(Ollama no disponible: {e}) — uso reglas simples")

    if extracted.get("intent") == "unknown" and _CREATE_HINT.search(transcript):
        extracted["intent"] = "create_client"

    if extracted.get("intent") != "create_client":
        return {
            "transcript": transcript,
            "extracted": extracted,
            "ready": False,
            "reply": "\n".join(reply_parts) + f"\n\n{_friendly_menu()}",
        }

    missing = []
    ruc = str(extracted.get("ruc") or "").strip()
    name = str(extracted.get("name") or "").strip()
    phone = normalize_phone_ec(str(extracted.get("phone") or ""))
    email = str(extracted.get("email") or "").strip()

    if validate_ruc_cedula(ruc):
        missing.append("ruc")
    if not name:
        missing.append("name")
    if phone and validate_phone_ec(phone):
        missing.append("phone")
    if email and validate_email(email):
        missing.append("email")

    extracted["missing_fields"] = list(set(missing + (extracted.get("missing_fields") or [])))

    if extracted["missing_fields"]:
        clar = extracted.get("clarification") or "Faltan datos obligatorios."
        return {
            "transcript": transcript,
            "extracted": extracted,
            "ready": False,
            "reply": "\n".join(reply_parts) + f"\n\n⚠️ No puedo crear aún. Falta: {', '.join(extracted['missing_fields'])}.\n{clar}",
        }

    dup = check_duplicate_client(ruc=ruc)
    if not dup.get("passed"):
        return {
            "transcript": transcript,
            "extracted": extracted,
            "ready": False,
            "reply": dup.get("message", "Cliente duplicado"),
        }

    if not confirm:
        return {
            "transcript": transcript,
            "extracted": extracted,
            "ready": True,
            "needs_confirm": True,
            "reply": "\n".join(reply_parts) + (
                f"\n\n✅ Propuesta de cliente:\n"
                f"• RUC: {ruc}\n• Nombre: {name}\n• Tel: {phone or '—'}\n• Email: {email or '—'}\n"
                f"\nResponde «confirmar» o pulsa Confirmar para grabar."
            ),
        }

    from api.crud_v1 import ClientIn, create_client

    doc = create_client(ClientIn(
        ruc=ruc,
        name=name,
        phone=phone,
        email=email,
        city=str(extracted.get("city") or ""),
        pais=str(extracted.get("pais") or "Ecuador"),
        estado=str(extracted.get("estado") or "Cliente"),
    ))
    return {
        "transcript": transcript,
        "extracted": extracted,
        "ready": True,
        "created": doc,
        "reply": f"Cliente creado: {doc['name']} (RUC {doc.get('ruc')})",
    }


@router.post("/voice/agent")
async def voice_agent(
    audio_file: UploadFile | None = File(None),
    text: str | None = None,
    confirm: bool = False,
):
    """Audio o texto → Whisper (si audio) → Ollama valida campos → confirmar antes de crear."""
    from tools.transcribe import transcribe_audio_file

    transcript = (text or "").strip()
    if audio_file and audio_file.filename:
        content = await audio_file.read()
        suffix = Path(audio_file.filename).suffix or ".webm"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            path = tmp.name
        try:
            tr = transcribe_audio_file(path)
            transcript = tr.get("text") or transcript
        finally:
            Path(path).unlink(missing_ok=True)

    if not transcript:
        raise HTTPException(400, "Sin audio ni texto")
    if confirm or transcript.lower().strip() in {"confirmar", "sí", "si", "ok", "dale"}:
        return _process_voice_text(transcript, confirm=True)
    return _process_voice_text(transcript, confirm=False)


@router.post("/voice/agent/text")
def voice_agent_text(body: VoiceTextIn):
    return _process_voice_text(body.text, confirm=body.confirm)
