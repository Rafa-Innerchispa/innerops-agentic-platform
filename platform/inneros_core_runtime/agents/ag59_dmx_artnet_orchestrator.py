"""AG-59 DMX Orchestrator - safe local bridge to the InnerOS DMX engine.

This module deliberately exposes only a small, allowlisted surface suitable for
operator and demo use. Raw DMX channels, universes, node addresses and arbitrary
effects are not part of the public contract.
"""

from __future__ import annotations

import json
import os
import unicodedata
import urllib.error
import urllib.request
from typing import Any

AGENT_ID = "AG-59"
_DEFAULT_BACKEND_URLS = (
    "http://127.0.0.1:18796",
    "http://192.168.1.5:18796",
    "http://192.168.1.5:8096",
    "http://127.0.0.1:8096",
)
_BACKEND_URL = os.getenv("INNEROS_DMX_ENGINE_URL", "").rstrip("/")
_TIMEOUT_SECONDS = float(os.getenv("INNEROS_DMX_TIMEOUT_SECONDS", "2.5"))

_SCENE_ALIASES = {
    "rainbow": "rainbow",
    "arcoiris": "rainbow",
    "arco iris": "rainbow",
    "frenzy": "frenzy",
    "fiesta": "frenzy",
    "morado uv": "morado_uv",
    "morado ultraviolet": "morado_uv",
    "purple uv": "morado_uv",
    "uv purple": "morado_uv",
    "morado_uv": "morado_uv",
    "rojo sangre": "rojo_sangre",
    "blood red": "rojo_sangre",
    "rojo_sangre": "rojo_sangre",
}

SAFE_SCENES = ("rainbow", "frenzy", "morado_uv", "rojo_sangre")
SAFE_COLORS = (
    "rojo",
    "verde",
    "azul",
    "amarillo",
    "magenta",
    "fucsia",
    "cian",
    "cyan",
    "celeste",
    "turquesa",
    "naranja",
    "ambar",
    "dorado",
    "violeta",
    "morado",
    "purpura",
    "rosa",
    "rosado",
    "blanco",
    "blanco_calido",
    "blanco_frio",
    "neon",
    "cyberpunk",
)
SAFE_TARGETS = ("todas", "all", "tachos", "beams", "pulpos", "bola_disco", "tacho_plantas", "tacho_escalera", "tacho_peces", "tacho_central")


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", (value or "").strip().lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch)).replace("-", " ")


def _canonical_scene(scene: str) -> str | None:
    normalized = " ".join(_normalize(scene).split())
    return _SCENE_ALIASES.get(normalized) or _SCENE_ALIASES.get(normalized.replace(" ", "_"))


def _candidate_backend_urls() -> list[str]:
    raw = os.getenv("INNEROS_DMX_ENGINE_URLS", "")
    urls = []
    if _BACKEND_URL:
        urls.append(_BACKEND_URL)
    urls.extend(u.strip().rstrip("/") for u in raw.split(",") if u.strip())
    urls.extend(_DEFAULT_BACKEND_URLS)
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        if url and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _safe_color(color: str) -> str | None:
    c = _normalize(color).replace(" ", "_")
    if c == "calido":
        c = "blanco_calido"
    if c == "frio":
        c = "blanco_frio"
    if c == "cyan":
        c = "cian"
    if c == "morado_uv":
        c = "morado"
    if c == "rojo_sangre":
        c = "rojo"
    if c in {"purpura", "violeta"}:
        c = "morado"
    return c if c in SAFE_COLORS else None


def _safe_target(target: str) -> str | None:
    t = _normalize(target).replace(" ", "_")
    return t if t in SAFE_TARGETS else None


def _safe_brightness(value: Any) -> int:
    try:
        return max(0, min(255, int(value)))
    except Exception:
        return 255


def _request_json(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    last_error = "dmx_backend_unavailable"
    for base_url in _candidate_backend_urls():
        request = urllib.request.Request(
            f"{base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
                body = response.read().decode("utf-8", errors="replace")
                decoded = json.loads(body) if body else {}
                if isinstance(decoded, dict):
                    decoded.setdefault("_backend_url", base_url)
                    return decoded
                return {"ok": False, "error": "invalid_backend_response", "_backend_url": base_url}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            last_error = type(exc).__name__
    return {"ok": False, "error": "dmx_backend_unavailable", "detail": last_error}


def dmx_status() -> dict[str, Any]:
    """Return a sanitized status snapshot. Never returns node IP or universe."""
    raw = _request_json("GET", "/api/status")
    if not raw.get("ok"):
        return {"ok": False, "agent_id": AGENT_ID, "status": "unavailable", "error": raw.get("error", "dmx_backend_unavailable")}
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "status": str(raw.get("status") or "online"),
        "running": bool(raw.get("running")),
        "current_scene": raw.get("current_effect"),
        "safe_scenes": list(raw.get("supported_scenes") or SAFE_SCENES),
        "safe_colors": list(SAFE_COLORS),
        "safe_targets": list(SAFE_TARGETS),
        "backend": "local_dmx_engine",
    }


def dmx_set_scene(scene: str = "", *, color: str = "", target: str = "todas", brightness: int = 255, speed: float = 1.0) -> dict[str, Any]:
    """Apply one allowlisted high-level scene or color; reject raw/arbitrary DMX input."""
    canonical = _canonical_scene(scene)
    safe_color = _safe_color(color or (scene if canonical is None else ""))
    safe_target = _safe_target(target or "todas")
    if canonical is None and safe_color is None:
        return {
            "ok": False,
            "agent_id": AGENT_ID,
            "error": "unsupported_scene",
            "requested_scene": (scene or "")[:80],
            "allowed_scenes": list(SAFE_SCENES),
            "allowed_colors": list(SAFE_COLORS),
        }
    if safe_target is None:
        return {
            "ok": False,
            "agent_id": AGENT_ID,
            "error": "unsupported_target",
            "requested_target": (target or "")[:80],
            "allowed_targets": list(SAFE_TARGETS),
        }

    if canonical in {"rainbow", "frenzy"}:
        raw = _request_json("POST", "/api/scene", {"mode": canonical, "speed": float(speed or 1.0)})
    elif canonical == "morado_uv":
        raw = _request_json("POST", "/api/color", {"color": "morado", "target": "todas", "brightness": 220})
    elif canonical == "rojo_sangre":
        raw = _request_json("POST", "/api/color", {"color": "rojo", "target": "todas", "brightness": 235})
    else:
        raw = _request_json(
            "POST",
            "/api/color",
            {"color": safe_color, "target": safe_target, "brightness": _safe_brightness(brightness)},
        )

    if not raw.get("ok"):
        return {"ok": False, "agent_id": AGENT_ID, "scene": canonical, "error": raw.get("error", "dmx_backend_unavailable")}
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "action": "set_scene",
        "scene": canonical or safe_color,
        "target": safe_target if canonical is None else "todas",
        "verified_backend_ack": True,
        "backend": "local_dmx_engine",
    }


def dmx_blackout() -> dict[str, Any]:
    """Trigger the engine's bounded all-fixture blackout operation."""
    raw = _request_json("POST", "/api/blackout", {})
    if not raw.get("ok"):
        return {"ok": False, "agent_id": AGENT_ID, "error": raw.get("error", "dmx_backend_unavailable")}
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "action": "blackout",
        "verified_backend_ack": True,
        "backend": "local_dmx_engine",
    }


def run_dmx_orchestrator(message: str = "", *, dry_run: bool = True, **_: Any) -> dict[str, Any]:
    """AG-59 runner. Unknown/casual text never changes physical state."""
    text = " ".join(_normalize(message).split())
    if not text or text in {"status", "estado", "health", "salud"}:
        return dmx_status()

    if text in {"blackout", "apagar dmx", "apaga dmx", "dmx blackout"}:
        if dry_run:
            return {"ok": True, "agent_id": AGENT_ID, "dry_run": True, "would_execute": "blackout"}
        return dmx_blackout()

    canonical = _canonical_scene(text)
    if canonical:
        if dry_run:
            return {"ok": True, "agent_id": AGENT_ID, "dry_run": True, "would_execute": "set_scene", "scene": canonical}
        return dmx_set_scene(canonical)

    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "action": "none",
        "message": "No physical action executed. Use status, blackout, or an allowlisted scene.",
        "allowed_scenes": list(SAFE_SCENES),
    }
