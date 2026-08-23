# Runtime AG-38 Vero
from __future__ import annotations

import os
from typing import Any

import yaml


def run(context_variables: dict[str, Any] | None = None) -> dict[str, Any]:
    from raphiia_openai.commercial import vero_orchestrator

    ctx = context_variables or {}
    message = str(ctx.get("message") or ctx.get("body") or "").strip()
    if not message:
        return {"ok": False, "error": "message_required", "agent_id": "AG-38"}
    return vero_orchestrator.vero_dispatch(
        message,
        channel=str(ctx.get("channel") or "agent_pool"),
        entity_id=str(ctx.get("entity_id") or "ent_pcdoctor"),
        require_approval=bool(ctx.get("require_approval", True)),
        approved_by=ctx.get("approved_by"),
        client_ref=ctx.get("client_ref"),
        quote_ref=ctx.get("quote_ref"),
        phone=ctx.get("phone"),
    )


def load_agent_config() -> dict[str, Any]:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(base_dir, "config", "agent.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)["vero_commercial_orchestrator"]
