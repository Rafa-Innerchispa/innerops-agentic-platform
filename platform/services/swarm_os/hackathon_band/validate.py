"""Validación de .env — sin keys no arranca el pipeline real."""

from __future__ import annotations

from typing import Any

from hackathon_band import config
from hackathon_band.exceptions import HackathonConfigError

_AGENT_ID_VARS = [
    "BAND_AGENT_ID_ROUTER",
    "BAND_AGENT_ID_MEMORY",
    "BAND_AGENT_ID_ANALYST",
    "BAND_AGENT_ID_DOCUMENTATION",
]

_AGENT_KEY_VARS = [
    "BAND_API_KEY_ROUTER",
    "BAND_API_KEY_MEMORY",
    "BAND_API_KEY_ANALYST",
    "BAND_API_KEY_DOCUMENTATION",
]

_VAR_MAP = {
    "BAND_AGENT_ID_ROUTER": lambda: config.BAND_AGENT_ID_ROUTER,
    "BAND_AGENT_ID_MEMORY": lambda: config.BAND_AGENT_ID_MEMORY,
    "BAND_AGENT_ID_ANALYST": lambda: config.BAND_AGENT_ID_ANALYST,
    "BAND_AGENT_ID_DOCUMENTATION": lambda: config.BAND_AGENT_ID_DOCUMENTATION,
    "BAND_API_KEY": lambda: config.BAND_API_KEY,
    "BAND_API_KEY_ROUTER": lambda: config.BAND_API_KEY_ROUTER,
    "BAND_API_KEY_MEMORY": lambda: config.BAND_API_KEY_MEMORY,
    "BAND_API_KEY_ANALYST": lambda: config.BAND_API_KEY_ANALYST,
    "BAND_API_KEY_DOCUMENTATION": lambda: config.BAND_API_KEY_DOCUMENTATION,
    "FEATHERLESS_API_KEY": lambda: config.FEATHERLESS_API_KEY,
    "AIML_API_KEY": lambda: config.AIML_API_KEY,
}


def _band_auth_ok() -> bool:
    if (config.BAND_API_KEY or "").strip():
        return True
    return all((_VAR_MAP[name]() or "").strip() for name in _AGENT_KEY_VARS)


def missing_vars() -> list[str]:
    out: list[str] = []
    for name in _AGENT_ID_VARS:
        if not (_VAR_MAP[name]() or "").strip():
            out.append(name)
    if not _band_auth_ok():
        if not (config.BAND_API_KEY or "").strip():
            out.append("BAND_API_KEY (o las 4 BAND_API_KEY_*)")
    for name in ("FEATHERLESS_API_KEY", "AIML_API_KEY"):
        if not (_VAR_MAP[name]() or "").strip():
            out.append(name)
    return out


def require_config() -> None:
    missing = missing_vars()
    if missing:
        raise HackathonConfigError(
            missing,
            hint=(
                "Rafael debe pegar las keys en .env del servidor "
                f"({config.REPO_ROOT / '.env'}). "
                "Ver hackathon_band/.env.example y docs/HACKATHON_BAND_OF_AGENTS.md"
            ),
        )


def readiness() -> dict[str, Any]:
    missing = missing_vars()
    hints: list[str] = []
    key = (config.BAND_API_KEY or "").strip()
    if key.startswith("band_u_"):
        hints.append(
            "BAND_API_KEY parece key de USUARIO (band_u_*). "
            "Usa BAND_API_KEY_ROUTER/MEMORY/ANALYST/DOCUMENTATION (band_a_*)."
        )
    return {
        "ready": not missing,
        "missing": missing,
        "hints": hints,
        "band_rest_url": config.BAND_REST_URL,
        "featherless_model": config.FEATHERLESS_MODEL,
        "aiml_model": config.AIML_MODEL,
    }
