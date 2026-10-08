"""Resolve ops task → real execution runner (fail-closed, no silent internal fallback)."""

from __future__ import annotations

from typing import Any

INTERACTIVE_IDE_PROVIDERS = frozenset({"cursor", "codex", "antigravity", "gemini", "chatgpt"})
INTERNAL_BOUNDED_RUNNER = "internal_bounded_local"
INTERACTIVE_IDE_RUNNER = "interactive_ide_handoff"
CURSOR_INTERACTIVE_RUNNER = "cursor_interactive"
BLOCKED_RUNNER = "blocked"
CURSOR_PINNED_MODEL = __import__("os").getenv("CURSOR_OPS_PINNED_MODEL", "composer-2.5-fast").strip()

_DISPATCH_KEYS = (
    "dispatch_mode",
    "do_not_auto_dispatch",
    "model_preflight_required",
    "automatic_model_fallback_allowed",
    "production_mutations_allowed",
    "contract_revision",
    "assignment_override",
    "source_message_id",
    "payload",
)


def normalize_provider(value: str | None) -> str:
    raw = str(value or "").strip().lower().replace("_", "-")
    aliases = {"anti-gravity": "antigravity", "google-antigravity": "antigravity", "codex-cli": "codex"}
    return aliases.get(raw, raw)


def merge_task_dispatch_fields(task: dict[str, Any]) -> dict[str, Any]:
    """Flatten nested payload dispatch controls onto the workflow envelope."""
    merged = dict(task or {})
    payload = dict(merged.get("payload") or {})
    if isinstance(merged.get("payload"), dict):
        for key in _DISPATCH_KEYS:
            if key == "payload":
                continue
            if key in payload and merged.get(key) in (None, "", {}):
                merged[key] = payload[key]
    if not merged.get("objective") and merged.get("body"):
        merged["objective"] = str(merged.get("body") or "")[:8000]
    if not merged.get("title") and merged.get("objective"):
        merged["title"] = str(merged["objective"])[:500]
    return merged


def resolve_execution_binding(envelope_dict: dict[str, Any]) -> dict[str, Any]:
    """Decide whether Temporal may run the internal bounded local path."""
    env = merge_task_dispatch_fields(envelope_dict)
    provider = normalize_provider(
        env.get("preferred_provider") or env.get("assignee") or env.get("assigned_to")
    )
    lane = str(env.get("execution_lane") or "").strip().lower()
    dispatch_mode = str(env.get("dispatch_mode") or "").strip().lower()
    do_not_auto = bool(env.get("do_not_auto_dispatch"))
    model_preflight = bool(env.get("model_preflight_required"))
    preferred_model = env.get("preferred_model")
    model_missing = preferred_model is None or str(preferred_model).strip() == ""

    base = {
        "provider_normalized": provider,
        "execution_lane": lane or None,
        "dispatch_mode": dispatch_mode or None,
        "do_not_auto_dispatch": do_not_auto,
        "model_preflight_required": model_preflight,
        "preferred_model": preferred_model,
    }

    owner_approved = bool(env.get("owner_approved") or env.get("owner_authorized_at"))
    if provider == "cursor" and (do_not_auto or dispatch_mode in {"owner_interactive_handoff", "interactive_handoff", "manual"}):
        return {
            **base,
            "ok": False,
            "allowed": False,
            "runner": CURSOR_INTERACTIVE_RUNNER,
            "status": "awaiting_cursor_claim",
            "error": "cursor_claim_required",
            "message": (
                "Temporal detenido. Usa cursor_claim_ops_task (owner_approved) en sesión Cursor; "
                f"modelo fijado {CURSOR_PINNED_MODEL}."
            ),
            "preferred_model_default": CURSOR_PINNED_MODEL,
        }

    if do_not_auto or dispatch_mode in {"owner_interactive_handoff", "interactive_handoff", "manual"}:
        return {
            **base,
            "ok": False,
            "allowed": False,
            "runner": BLOCKED_RUNNER,
            "status": "waiting_for_binding",
            "error": "do_not_auto_dispatch",
            "message": (
                "Auto-dispatch bloqueado: requiere ejecutor interactivo (Cursor/owner). "
                "Temporal no debe usar el carril internal genérico."
            ),
        }

    if model_preflight and model_missing:
        return {
            **base,
            "ok": False,
            "allowed": False,
            "runner": BLOCKED_RUNNER,
            "status": "waiting_for_model_binding",
            "error": "preferred_model_missing",
            "message": "model_preflight_required pero preferred_model no está fijado en el contrato.",
        }

    if provider in INTERACTIVE_IDE_PROVIDERS:
        if lane in {"", "internal", "mcp"}:
            return {
                **base,
                "ok": False,
                "allowed": False,
                "runner": INTERACTIVE_IDE_RUNNER,
                "status": "waiting_for_binding",
                "error": "interactive_provider_requires_ide_runner",
                "message": (
                    f"preferred_provider={provider} no puede ejecutarse por carril internal/local genérico. "
                    "Use sesión IDE o runner explícito."
                ),
            }
        if provider == "cursor" and lane in {"interactive_ide", "owner_handoff", "cursor_session", "cursor_interactive", "external_ide"}:
            return {
                **base,
                "ok": False,
                "allowed": False,
                "runner": CURSOR_INTERACTIVE_RUNNER,
                "status": "awaiting_cursor_claim",
                "error": "cursor_claim_required",
                "message": f"Esperando cursor_claim_ops_task en sesión activa (modelo {CURSOR_PINNED_MODEL}).",
                "preferred_model_default": CURSOR_PINNED_MODEL,
            }
        if lane in {"interactive_ide", "owner_handoff", "cursor_session", "external_ide"}:
            return {
                **base,
                "ok": False,
                "allowed": False,
                "runner": INTERACTIVE_IDE_RUNNER,
                "status": "waiting_for_binding",
                "error": "interactive_handoff_pending",
                "message": f"Esperando claim/ejecución en sesión {provider}.",
            }

    if lane in {"internal", "local_dev_swarm", "dev_swarm"} or provider in {
        "local",
        "local-amd-5",
        "dev_swarm",
        "dev-swarm",
        "temporal",
    }:
        return {
            **base,
            "ok": True,
            "allowed": True,
            "runner": INTERNAL_BOUNDED_RUNNER,
            "status": "ready",
            "error": None,
            "message": "internal_bounded_local permitted",
        }

    return {
        **base,
        "ok": False,
        "allowed": False,
        "runner": BLOCKED_RUNNER,
        "status": "waiting_for_binding",
        "error": "execution_binding_unresolved",
        "message": f"No hay runner confirmado para provider={provider} lane={lane or 'unset'}.",
    }
