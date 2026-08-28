"""Persistent External Repair Agent daemon.

Default mode is monitor-only. Set EXTERNAL_REPAIR_AUTO_CLAIM=1 and
EXTERNAL_REPAIR_OWNER_AUTHORIZED=1 to allow provider-ready tasks to be claimed;
execution still requires explicit approval.
"""

from __future__ import annotations

import os
import socket
import time

from raphiia_openai import external_repair_agent, mongo_store

STATE_KEY_PREFIX = "external_repair_agent_daemon"


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def tick() -> dict:
    provider = os.getenv("EXTERNAL_REPAIR_PROVIDER", "codex")
    auto_claim = _bool_env("EXTERNAL_REPAIR_AUTO_CLAIM", False)
    node = socket.gethostname()
    reconcile = external_repair_agent.external_repair_agent_reconcile(
        provider=provider,
        auto_claim=auto_claim,
        dry_run=not auto_claim,
        limit=10,
    )
    payload = {
        "ok": True,
        "node": node,
        "provider": provider,
        "auto_claim": auto_claim,
        "reconcile": reconcile,
        "status": reconcile.get("status_after"),
        "recovery": reconcile.get("recovered"),
        "claim": reconcile.get("claim"),
        "mode": "auto_claim" if auto_claim else "monitor_only",
    }
    mongo_store.upsert_coordination_state(key=f"{STATE_KEY_PREFIX}:{node}", data=payload)
    return payload


def main() -> None:
    interval = max(15, int(os.getenv("EXTERNAL_REPAIR_INTERVAL_SEC", "120")))
    while True:
        try:
            tick()
        except Exception as exc:
            node = socket.gethostname()
            mongo_store.upsert_coordination_state(key=f"{STATE_KEY_PREFIX}:{node}", data={"ok": False, "node": node, "error": str(exc)[:500]})
        time.sleep(interval)


if __name__ == "__main__":
    main()
