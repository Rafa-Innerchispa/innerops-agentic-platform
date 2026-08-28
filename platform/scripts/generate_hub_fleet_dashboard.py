#!/usr/bin/env python3
"""Genera HUB/AGENT_FLEET_STATUS.md — dashboard flota AG local."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OUT = os.path.expanduser("~/data/ai_coordination/HUB/AGENT_FLEET_STATUS.md")


def main() -> int:
    from raphiia_openai import coordination_live, mcp_fleet, mongo_store
    from raphiia_openai.agents import agent_catalog
    from raphiia_openai.agents.pool_agent_runners import get_runner_registry, invoke_agent

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    runners = get_runner_registry()
    catalog = agent_catalog.get_agent_catalog(functional_only=False)
    live = coordination_live.get_coordination_live()
    fleet = mcp_fleet.fleet_status()
    mongo = mongo_store.ping_mongo()
    guardian = invoke_agent("AG-42", "", dry_run=False)

    lines = [
        f"# Flota AG — {now}",
        "",
        "## Resumen",
        f"- Runners: **{len(runners)}**",
        f"- Catálogo functional: **{sum(1 for a in catalog.get('agents', []) if a.get('status') == 'functional')}**",
        f"- Coordinación rev: **{live.get('revision')}** | ops abiertas: **{live.get('open_ops_count')}**",
        f"- Mongo: **{'OK' if mongo.get('ok') else 'FAIL'}**",
        f"- Nodo local: **{fleet.get('local_node')}**",
        f"- Guardian: **{'OK' if guardian.get('ok') else 'DEGRADED'}**",
        "",
        "## Nodos MCP",
    ]
    for node, info in (fleet.get("nodes") or {}).items():
        lines.append(f"- **{node}** ({info.get('host')}): tcp={info.get('tcp_ok')} mcp={info.get('mcp_ok')}")

    lines.extend(["", "## Agentes por dominio", ""])
    by_domain: dict[str, list[str]] = {}
    for a in catalog.get("agents") or []:
        dom = a.get("domain") or "other"
        aid = a.get("agent_id", "?")
        name = a.get("display_name", "")
        by_domain.setdefault(dom, []).append(f"{aid} {name}")

    for dom in sorted(by_domain.keys()):
        lines.append(f"### {dom}")
        for entry in sorted(by_domain[dom])[:20]:
            lines.append(f"- {entry}")
        lines.append("")

    lines.extend([
        "## Entrada",
        "- `ralfia_dispatch(mensaje)` · `invoke_agent('AG-XX')` · WhatsApp NL → ralfia_dispatch",
        "- Scripts: `validate_all_agents.py` · `run_agent_integration_tests.py` · `run_rigor_tests.py`",
        "",
        "_Generado localmente — sin créditos cloud._",
    ])

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
