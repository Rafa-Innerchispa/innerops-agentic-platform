"""Perfil por usuario — gustos, hechos aprendidos, contexto personal (estilo ChatGPT memory).

Importación ChatGPT: si existe conversations.json del export oficial, ejecutar
  python3 ralfiia-amd-standby/scripts/import_chatgpt_export_voice.py <ruta>
(Búsqueda 2026-08-01 en ~/data, ~/Downloads, ~/projects: no se encontró export.)
"""

from __future__ import annotations

import re
import time
from typing import Any

from raphiia_openai import daily_memory, mongo_store
from raphiia_openai.settings import RALFIA_OWNER_ID

COL_PROFILES = "ralfia_voice_user_profiles"
RAFAEL_USERNAMES = frozenset({"rafagye", "rlopez", "admin", "rafael"})

_LEARN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?:me gusta|me encanta|prefiero|odio|no me gusta)\s+(.{3,120})", re.I), "preference"),
    (re.compile(r"(?:soy|trabajo en|mi rol es|me dedico a)\s+(.{3,120})", re.I), "role"),
    (re.compile(r"(?:necesito|quiero|busco|mi objetivo es)\s+(.{3,120})", re.I), "need"),
    (re.compile(r"(?:recuerda que|no olvides que|importante:)\s+(.{3,200})", re.I), "note"),
]


def is_rafael(user: dict[str, Any]) -> bool:
    uname = str(user.get("username") or "").lower().split("@")[0]
    owner = str(user.get("owner_id") or "").upper()
    if uname in RAFAEL_USERNAMES or owner == RALFIA_OWNER_ID:
        return True
    email = str(user.get("email") or user.get("username") or "").lower()
    return email in ("rafagye@gmail.com", "rafagye")


def _db():
    return mongo_store.get_db()


def get_profile(username: str) -> dict[str, Any]:
    doc = _db()[COL_PROFILES].find_one({"username": username.lower()}, {"_id": 0}) or {}
    return {
        "username": username.lower(),
        "display_name": doc.get("display_name") or username,
        "facts": list(doc.get("facts") or [])[-30:],
        "preferences": dict(doc.get("preferences") or {}),
        "interaction_count": int(doc.get("interaction_count") or 0),
        "first_seen": doc.get("first_seen"),
        "last_seen": doc.get("last_seen"),
    }


def touch_profile(user: dict[str, Any]) -> None:
    uname = str(user.get("username") or "").lower()
    if not uname:
        return
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _db()[COL_PROFILES].update_one(
        {"username": uname},
        {
            "$set": {
                "display_name": user.get("display_name") or uname,
                "owner_id": user.get("owner_id"),
                "last_seen": now,
            },
            "$inc": {"interaction_count": 1},
            "$setOnInsert": {"first_seen": now, "facts": [], "preferences": {}},
        },
        upsert=True,
    )


def learn_from_message(user: dict[str, Any], content: str) -> None:
    """Extrae hechos simples del mensaje del usuario (sin LLM)."""
    text = (content or "").strip()
    if len(text) < 8:
        return
    uname = str(user.get("username") or "").lower()
    if not uname:
        return
    owner_id = RALFIA_OWNER_ID if is_rafael(user) else str(user.get("owner_id") or uname.upper())
    scope = "PRIVATE_PERSONAL" if is_rafael(user) else "INTERNAL_WORK"
    new_facts: list[str] = []
    for pat, kind in _LEARN_PATTERNS:
        m = pat.search(text)
        if m:
            snippet = m.group(1).strip().rstrip(".")
            if snippet and len(snippet) > 3:
                new_facts.append(f"[{kind}] {snippet}")
    if not new_facts:
        return
    db = _db()
    doc = db[COL_PROFILES].find_one({"username": uname}, {"facts": 1}) or {}
    existing = list(doc.get("facts") or [])
    for f in new_facts:
        if f not in existing:
            existing.append(f)
    existing = existing[-40:]
    db[COL_PROFILES].update_one(
        {"username": uname},
        {"$set": {"facts": existing, "last_seen": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}},
        upsert=True,
    )
    for f in new_facts[:2]:
        try:
            daily_memory.save_memory(
                {
                    "body": f"Perfil voz {uname}: {f}",
                    "kind": "fact",
                    "privacy_scope": scope,
                    "owner_id": owner_id,
                    "actor": uname.upper(),
                    "project": "ralfia_voice_profile",
                }
            )
        except Exception:
            pass


def profile_context_block(user: dict[str, Any]) -> str:
    uname = str(user.get("username") or "").lower()
    if not uname:
        return ""
    prof = get_profile(uname)
    facts = prof.get("facts") or []
    if not facts:
        return ""
    lines = [f"=== Lo que sabes de {prof.get('display_name') or uname} (aprendido en conversaciones) ==="]
    for f in facts[-12:]:
        lines.append(f"- {f}")
    if is_rafael(user):
        lines.append("Trata a Rafael con confianza total — es el dueño. Usa «tú», «tu yo del futuro».")
    else:
        lines.append(
            "Este usuario NO es Rafael. Preséntate como el yo del futuro DE Rafael, "
            "conoce sus gustos y trátalo con calidez profesional."
        )
    return "\n".join(lines)
