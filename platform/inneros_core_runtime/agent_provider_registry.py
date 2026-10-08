"""Registro extensible de agentes IDE/internos — integración automática de agentes nuevos."""

from __future__ import annotations

import os
import re
from typing import Any

from inneros_core_runtime import agent_identity

_DEFAULT_IDE = frozenset({"cursor", "codex", "antigravity", "gemini", "chatgpt"})
_DEFAULT_INTERNAL = frozenset({"local", "dev_swarm", "dev-swarm", "temporal", "local-amd-5"})

_REGISTRY: dict[str, dict[str, Any]] = {}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "_", (name or "").strip().lower()).strip("_")


def _load_env_extra() -> None:
    extra = os.getenv("INTERACTIVE_IDE_PROVIDERS_EXTRA", "")
    for raw in extra.split(","):
        key = _slug(raw)
        if key:
            register_interactive_provider(key)


def register_interactive_provider(
    provider: str,
    *,
    default_lane: str | None = None,
    pinned_model_env: str | None = None,
    claim_tool: str | None = None,
    complete_tool: str | None = None,
) -> dict[str, Any]:
    """Registra un agente IDE nuevo sin tocar código core."""
    key = agent_identity.canonical_mailbox(provider, default=_slug(provider))
    lane = default_lane or f"{key}_interactive"
    doc = {
        "provider": key,
        "kind": "interactive_ide",
        "default_lane": lane,
        "pinned_model_env": pinned_model_env or f"{key.upper()}_OPS_PINNED_MODEL",
        "claim_tool": claim_tool or f"{key}_claim_ops_task",
        "complete_tool": complete_tool or f"{key}_complete_ops_task",
        "do_not_auto_dispatch_default": True,
    }
    _REGISTRY[key] = doc
    return {"ok": True, "registered": doc}


def register_internal_provider(provider: str, *, default_lane: str = "local_dev_swarm") -> dict[str, Any]:
    key = _slug(provider)
    doc = {"provider": key, "kind": "internal_bounded", "default_lane": default_lane, "do_not_auto_dispatch_default": False}
    _REGISTRY[key] = doc
    return {"ok": True, "registered": doc}


def interactive_providers() -> frozenset[str]:
    _load_env_extra()
    keys = set(_DEFAULT_IDE) | {k for k, v in _REGISTRY.items() if v.get("kind") == "interactive_ide"}
    return frozenset(keys)


def internal_providers() -> frozenset[str]:
    keys = set(_DEFAULT_INTERNAL) | {k for k, v in _REGISTRY.items() if v.get("kind") == "internal_bounded"}
    return frozenset(keys)


def provider_spec(provider: str) -> dict[str, Any] | None:
    key = agent_identity.canonical_mailbox(provider, default=_slug(provider))
    return _REGISTRY.get(key)


def apply_create_ops_defaults(
    assignee: str,
    *,
    execution_lane: str | None,
    preferred_provider: str | None,
    do_not_auto_dispatch: bool | None,
) -> tuple[str | None, str | None, bool | None]:
    """Defaults al crear ops task para agentes registrados o IDE conocidos."""
    prov = agent_identity.canonical_mailbox(preferred_provider or assignee)
    lane = (execution_lane or "").strip().lower() or None
    spec = provider_spec(prov)
    if spec:
        lane = lane or str(spec.get("default_lane") or "")
        if do_not_auto_dispatch is None:
            do_not_auto_dispatch = bool(spec.get("do_not_auto_dispatch_default"))
    elif prov in _DEFAULT_IDE:
        if not lane:
            lane = f"{prov}_interactive" if prov in {"cursor", "codex"} else "interactive_ide"
        if do_not_auto_dispatch is None:
            do_not_auto_dispatch = True
    elif prov in internal_providers() and not lane:
        lane = "local_dev_swarm"
    return lane or None, prov, do_not_auto_dispatch


# Bootstrap conocidos
register_interactive_provider("cursor", default_lane="cursor_interactive", pinned_model_env="CURSOR_OPS_PINNED_MODEL")
register_interactive_provider("codex", default_lane="codex_interactive", pinned_model_env="CODEX_OPS_PINNED_MODEL")
_load_env_extra()
