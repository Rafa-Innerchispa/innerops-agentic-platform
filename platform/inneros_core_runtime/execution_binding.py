"""Resolve ops task → real execution runner (fail-closed, no silent internal fallback)."""

from __future__ import annotations

from typing import Any

def _interactive_ide_providers() -> frozenset[str]:
    from inneros_core_runtime import agent_provider_registry as apr

    return apr.interactive_providers()


# Compat: usar agent_provider_registry.interactive_providers() en runtime
INTERACTIVE_IDE_PROVIDERS = frozenset({"cursor", "codex", "antigravity", "gemini", "chatgpt"})


def _ide_providers() -> frozenset[str]:
    try:
        return _interactive_ide_providers()
    except Exception:
        return INTERACTIVE_IDE_PROVIDERS
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


def _pinned_model(provider: str) -> str:
    from inneros_core_runtime import interactive_ops_runner as ior

    return ior.pinned_model(provider)


def _interactive_claim_active(env: dict[str, Any], provider: str) -> bool:
    if provider not in _ide_providers():
        return False
    status = str(env.get("status") or "").lower()
    return status in {"claimed", "running", "verification"} and bool(str(env.get("claim_token") or "").strip())


def _cursor_claim_active(env: dict[str, Any], provider: str) -> bool:
    return provider == "cursor" and _interactive_claim_active(env, provider)


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
    effective_model = env.get("effective_model") or preferred_model
    model_missing = preferred_model is None or str(preferred_model).strip() == ""

    base = {
        "provider_normalized": provider,
        "execution_lane": lane or None,
        "dispatch_mode": dispatch_mode or None,
        "do_not_auto_dispatch": do_not_auto,
        "model_preflight_required": model_preflight,
        "preferred_model": preferred_model,
    }

    if _interactive_claim_active(env, provider):
        expected_model = _pinned_model(provider)
        pinned_ok = str(effective_model or preferred_model or "").strip() == expected_model
        runner = CURSOR_INTERACTIVE_RUNNER if provider == "cursor" else INTERACTIVE_IDE_RUNNER
        if model_preflight and not pinned_ok:
            return {
                **base,
                "ok": False,
                "allowed": False,
                "runner": runner,
                "status": "blocked",
                "error": f"{provider}_model_not_accredited",
                "message": f"Modelo acreditado requerido: {expected_model}.",
            }
        complete_tool = f"{provider}_complete_ops_task"
        return {
            **base,
            "ok": True,
            "allowed": False,
            "runner": runner,
            "status": str(env.get("status") or "claimed"),
            "error": None,
            "interactive_execution": True,
            "message": (
                f"Claim {provider} activo: ejecución IDE; cierre con {complete_tool} + evidencia (Temporal gate)."
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

    owner_approved = bool(env.get("owner_approved") or env.get("owner_authorized_at"))
    if provider == "codex" and (do_not_auto or dispatch_mode in {"owner_interactive_handoff", "interactive_handoff", "manual"}):
        codex_model = str(
            __import__("os").getenv("CODEX_OPS_PINNED_MODEL", __import__("os").getenv("CODEX_WHATSAPP_MODEL", "gpt-5.6-sol"))
        ).strip()
        return {
            **base,
            "ok": False,
            "allowed": False,
            "runner": INTERACTIVE_IDE_RUNNER,
            "status": "awaiting_codex_claim",
            "error": "codex_claim_required",
            "message": f"Temporal detenido. Usa codex_claim_ops_task (owner_approved); modelo {codex_model}.",
            "preferred_model_default": codex_model,
        }

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

    if provider in _ide_providers() - {"cursor", "codex"} and (
        do_not_auto or dispatch_mode in {"owner_interactive_handoff", "interactive_handoff", "manual"}
    ):
        pin = _pinned_model(provider)
        return {
            **base,
            "ok": False,
            "allowed": False,
            "runner": INTERACTIVE_IDE_RUNNER,
            "status": f"awaiting_{provider}_claim",
            "error": f"{provider}_claim_required",
            "message": (
                f"Temporal detenido. Usa {provider}_claim_ops_task o {provider}_owner_order "
                f"(owner_approved); modelo fijado {pin or 'env'}."
            ),
            "preferred_model_default": pin or None,
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

    if provider in _ide_providers():
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
        if provider == "codex" and lane in {"interactive_ide", "codex_interactive", "owner_handoff", "external_ide"}:
            return {
                **base,
                "ok": False,
                "allowed": False,
                "runner": INTERACTIVE_IDE_RUNNER,
                "status": "awaiting_codex_claim",
                "error": "codex_claim_required",
                "message": "Esperando codex_claim_ops_task con owner_approved.",
            }
        ide_lane = f"{provider}_interactive"
        if provider in _ide_providers() - {"cursor", "codex"} and lane in {
            "interactive_ide",
            ide_lane,
            "owner_handoff",
            "external_ide",
        }:
            pin = _pinned_model(provider)
            return {
                **base,
                "ok": False,
                "allowed": False,
                "runner": INTERACTIVE_IDE_RUNNER,
                "status": f"awaiting_{provider}_claim",
                "error": f"{provider}_claim_required",
                "message": f"Esperando {provider}_claim_ops_task con owner_approved (modelo {pin or 'env'}).",
                "preferred_model_default": pin or None,
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
        # The internal bounded runner creates a governed Git worktree. Without
        # a real owner/repo it cannot execute an infrastructure request, even
        # when a local model generates convincing instructions.
        repo_ref = str(env.get("repo") or env.get("related_project") or "").strip()
        valid_repo_ref = (
            len(repo_ref.split("/")) == 2
            and all(part and not part.startswith(".") for part in repo_ref.split("/"))
            and all(c.isalnum() or c in "._-" for c in repo_ref)
        )
        if not valid_repo_ref and lane != "canary":
            return {
                **base,
                "ok": False,
                "allowed": False,
                "runner": BLOCKED_RUNNER,
                "status": "waiting_for_binding",
                "error": "bounded_runner_requires_repo",
                "message": (
                    "No hay repositorio owner/repo registrado para el ejecutor "
                    "interno. Una tarea de operaciones de host requiere un "
                    "ejecutor autorizado y evidencia real; no se simulara "
                    "un worktree ni se aceptara una respuesta del modelo."
                ),
            }
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


def _claim_error_es(provider: str) -> str:
    return (
        f"Requiere sesión {provider} activa y autorización owner (claim); no se usa runner interno."
    )


_ERROR_ES: dict[str, str] = {
    "cursor_claim_required": "Requiere sesión Cursor activa y autorización owner (claim); no se usa runner interno.",
    "codex_claim_required": "Requiere claim Codex con owner_approved; no se usa runner interno.",
    "antigravity_claim_required": _claim_error_es("Antigravity"),
    "gemini_claim_required": _claim_error_es("Gemini"),
    "chatgpt_claim_required": _claim_error_es("ChatGPT"),
    "do_not_auto_dispatch": "Auto-dispatch desactivado: debe ejecutar un agente interactivo o el owner.",
    "preferred_model_missing": "Falta fijar preferred_model con model_preflight_required.",
    "interactive_provider_requires_ide_runner": (
        "El proveedor es un IDE/agente externo; el carril internal no puede ejecutarlo en su lugar."
    ),
    "interactive_handoff_pending": "Esperando handoff en sesión IDE del proveedor asignado.",
    "execution_binding_unresolved": "No hay runner confirmado para la combinación provider + lane.",
}


def preview_internal_dev_swarm_route(envelope_dict: dict[str, Any]) -> dict[str, Any]:
    """Si la tarea tuviera provider dev_swarm + lane local, ¿sería internal permitido?"""
    env = merge_task_dispatch_fields(envelope_dict)
    if not str(env.get("repo") or "").strip():
        return {"ok": False, "feasible": False, "reason": "sin repo no hay contrato Dev Swarm acotado"}
    alt = {
        **env,
        "preferred_provider": "dev_swarm",
        "assignee": "dev_swarm",
        "assigned_to": "dev_swarm",
        "execution_lane": "local_dev_swarm",
        "do_not_auto_dispatch": False,
        "dispatch_mode": "",
    }
    binding = resolve_execution_binding(alt)
    feasible = bool(binding.get("allowed"))
    return {
        "ok": True,
        "feasible": feasible,
        "binding": binding,
        "reason": "Dev Swarm local acotado en repo" if feasible else str(binding.get("message") or ""),
    }


def owner_execution_summary(
    envelope_dict: dict[str, Any],
    binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Texto owner: por qué no interno, alternativa interna, siguiente acción WhatsApp."""
    env = merge_task_dispatch_fields(envelope_dict)
    binding = binding or resolve_execution_binding(env)
    provider = str(binding.get("provider_normalized") or normalize_provider(env.get("preferred_provider")) or "?")
    lane = str(binding.get("execution_lane") or env.get("execution_lane") or "—")
    err = str(binding.get("error") or "")
    why = _ERROR_ES.get(err) or str(binding.get("message") or "Revisar contrato de ejecución.")
    internal = preview_internal_dev_swarm_route(env)
    corr = str(env.get("correlation_id") or env.get("task_id") or "").strip()
    model = str(binding.get("preferred_model") or env.get("preferred_model") or binding.get("preferred_model_default") or "")

    if provider == "cursor":
        action = f"procede cursor {corr}".strip() if corr else "procede cursor"
        action_detail = f"Responde *{action}* y luego *confirmar co_…* (o MCP cursor_owner_order)."
    elif provider == "codex":
        action = f"codex_claim_ops_task / MCP codex_owner_order (correlación {corr})" if corr else "codex_owner_order"
        action_detail = f"Autoriza y claim Codex; modelo {model or 'gpt-5.6-sol'}."
    elif provider in _ide_providers():
        pin = model or _pinned_model(provider)
        action = f"{provider}_owner_order (correlación {corr})" if corr else f"{provider}_owner_order"
        action_detail = f"MCP {provider}_claim_ops_task con owner_approved; modelo {pin or 'env'}."
    else:
        action = "autoriza vía MCP o ajusta assignee/lane en la ops task"
        action_detail = action

    internal_line = (
        "Alternativa interna (Dev Swarm): sí, mismo repo con provider=dev_swarm y lane=local_dev_swarm."
        if internal.get("feasible")
        else f"Alternativa interna: no recomendada ({internal.get('reason', 'n/a')})."
    )

    return {
        "provider": provider,
        "execution_lane": lane,
        "runner": binding.get("runner"),
        "allowed_internal_runner": bool(binding.get("allowed")),
        "expected_status": binding.get("status"),
        "error_code": err or None,
        "why_not_internal": why,
        "internal_alternative": internal_line,
        "owner_action_hint": action_detail,
        "preferred_model": model or None,
        "requires_owner_authorization": not bool(binding.get("allowed"))
        or provider in _ide_providers()
        or bool(binding.get("do_not_auto_dispatch")),
    }
