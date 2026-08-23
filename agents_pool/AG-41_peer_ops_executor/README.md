# AG-41 Peer Ops Executor

Mutaciones **allowlisted** en nodos dual (.4 / .5) expuestas vía MCP.

- Status / snapshot: read-only
- Restart/start/recover: write (requiere API key / scope write)
- Logs: journalctl / docker logs (máx 50 líneas)

Base: `whatsapp_service_ops.py` + SSH identity `ralfia_peer_ops_ed25519`.

Runbook: `HUB/ROADMAP_AGENTES_UNIVERSAL_2026-08-12.md`
