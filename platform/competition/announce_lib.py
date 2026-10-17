"""Home Assistant → Echo (Alexa) via notify.send_message."""
from __future__ import annotations

import os
from typing import Any

DEFAULT_ECHO = "notify.echo_cuarto_speak"


def announce_phrase(phrase: str, *, echo_entity: str | None = None) -> dict[str, Any]:
    text = (phrase or "").strip()
    if not text:
        return {"ok": False, "error": "empty_phrase"}
    entity = (echo_entity or os.getenv("RALFIA_COMPETITION_ECHO", DEFAULT_ECHO)).strip() or DEFAULT_ECHO
    from raphiia_openai import homeassistant_client as ha

    return ha.call_service(
        "notify",
        "send_message",
        entity_id=entity,
        data={"message": text[:900]},
    )
