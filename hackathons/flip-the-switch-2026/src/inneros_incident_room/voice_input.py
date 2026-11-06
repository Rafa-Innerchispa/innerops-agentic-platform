"""Turn a few explicit Spanish dictation phrases into SAFE Switch room commands.

Wispr Flow (or any speech-to-text tool) inserts text into Switch. This module
receives only text. It never listens to the microphone, contacts Wispr, infers
entity identities, approves an action, or calls Home Assistant.
"""
from __future__ import annotations

import re
import unicodedata


ENTITY = r"(light\.[a-z0-9_]+)"


def _plain(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    without_accents = "".join(c for c in normalized if not unicodedata.combining(c))
    without_punctuation = without_accents.lower().replace(",", " ").strip().strip(".?!\u00bf\u00a1 ")
    return re.sub(r"\s+", " ", without_punctuation)


def to_safe_room_command(message: str) -> str:
    """Return a safe canonical command, or original text for the normal parser.

    Voice requests can *read* live HA data and *propose* a change. A separate,
    exact, typed or pasted ``!approve HA-...`` remains necessary to mutate.
    Ambiguous room phrases never select a light or bypass the approval gate.
    """
    original = message.strip()
    if not original or original[0] in ("!", "/"):
        return original
    spoken = _plain(original)
    if spoken.endswith(" por favor"):
        spoken = spoken[:-10]
    if spoken in {
        "que luces hay", "que luces tengo", "mostrar luces", "mostrar las luces",
        "muestra las luces", "muestrame las luces", "listar luces",
        "listar las luces", "consulta las luces", "consultar las luces",
    }:
        return "!lights"
    if spoken in {"consulta inneros", "consultar inneros", "estado de inneros"}:
        return "!inneros"
    if spoken in {"estado del agente", "estado del puente"}:
        return "!status"
    read = re.fullmatch(
        r"(?:estado de|consultar estado de|consulta el estado de|consulta estado de) " + ENTITY,
        spoken,
    )
    if read:
        return "!state " + read.group(1)
    propose = re.fullmatch(
        r"(?:proponer|propongo|quiero proponer) (encender|apagar) " + ENTITY,
        spoken,
    )
    if propose:
        return f"!propose {propose.group(2)} {'on' if propose.group(1) == 'encender' else 'off'}"
    return original