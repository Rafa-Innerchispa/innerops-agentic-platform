# MCP Small canonical OAuth recovery — 2026-09-30

## Production contract

- Public MCP URL and protected resource: `https://mcp.pcdoctor.ai/router/mcp`
- Authorization server: `https://auth.pcdoctor.ai`
- Public profile: `chatgpt_compact`
- Public tool projection: 23 tools
- Internal catalog: 693 tools; never publish this catalog directly to normal clients

## Root cause

The standalone router exposed protected-resource metadata only at a path under `/router/mcp`, while RFC 9728 clients also probe `/.well-known/oauth-protected-resource/router/mcp`. Cloudflare sent that standards-based path to the inactive 8102 origin. After routing was repaired, the 8112 compact backend still accepted only the legacy resources `https://mcp-chatgpt.creatorcore.ai/mcp` and `https://mcp.pcdoctor.ai/mcp`, rejecting the canonical token before tool execution.

## Live repair

1. Added `/.well-known/oauth-protected-resource/router/mcp` to the standalone router.
2. Routed that exact Cloudflare ingress path to `http://127.0.0.1:8250`.
3. Bound the `chatgpt_compact` backend to the canonical resource in its profile environment file.
4. Preserved legacy resources temporarily through an explicit allowlist. No wildcard was introduced.
5. Kept PKCE S256, exact redirects, scope checks, token expiry, refresh flow, and exact resource validation enabled.

## Real-client canary

PASS from the canonical Notion connection using the same OAuth flow used by external clients:

- `mcp_version`
- `get_coordination_live`
- `bootstrap_context`
- `device_fabric_providers`
- `bellini_guardian_status`
- `device_fabric_get(device_ref="192.168.3.1")`
- `diagnose_mcp_session`: 23/23 projected tools; no stale catalog or reauthorization required
- `dev_swarm_scheduler_status`: enabled; AMD primary and Intel secondary

## Security and rollout

MCP Full remains an internal backend/break-glass surface and must not be connected as a normal 693-tool client. MCP Small is the canonical public endpoint. Broad rollout remains gated on importing the standalone router source into Git, capability coverage accounting, public dual-node failover, and removal of legacy OAuth resources after migration.

## Reproducible public audit

Run:

```bash
python3 scripts/audit_p0_mcp_small_public_oauth.py
```

The audit is read-only and requires no token.
