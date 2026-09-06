# MCP Compact Surface

Date: 2026-09-06

## Purpose

Normal ChatGPT sessions, voice clients, and small local models should not load
the full InnerOS MCP catalog by default. They should start from a compact
profile that can inspect coordination state, read the inbox, discover agents,
and request a domain profile through `route_mcp_tools`.

## Live Surfaces

- Full owner/admin MCP: `https://mcp.pcdoctor.ai/mcp` -> Intel `:8102`.
- ChatGPT compact MCP: `https://mcp-chatgpt.creatorcore.ai/mcp` -> Intel `:8112`.
- Local compact MCP on both nodes:
  - Intel: `http://192.168.1.4:8112/mcp`
  - AMD: `http://192.168.1.5:8112/mcp`

## Compact Profile

`chatgpt_compact` publishes 12 tools:

- `mcp_version`
- `diagnose_mcp_session`
- `list_mcp_tool_profiles`
- `route_mcp_tools`
- `bootstrap_context`
- `get_coordination_live`
- `poll_agent_inbox`
- `list_ops_tasks`
- `create_agent_message`
- `a2a_status`
- `a2a_agent_cards`
- `get_agent_catalog`

## Usage Policy

- Use `chatgpt_compact` as the default connector for ordinary ChatGPT sessions.
- Use `route_mcp_tools` with `requested_profile` or intent text to select the
  next bounded profile.
- Use `max_tools` and `for_model` for small, local, voice, or slow sessions.
- Keep the full MCP endpoint for owner/admin/debug and advanced IDE agents.
- Execution still requires `X-API-Key` or OAuth Bearer; unauthenticated external
  calls can list the compact tools but cannot execute protected tools.

## Verification

2026-09-06 live verification:

- Intel `:8112` MCP `tools/list`: 12 tools.
- AMD `:8112` MCP `tools/list`: 12 tools.
- Public `https://mcp-chatgpt.creatorcore.ai/mcp` MCP `tools/list`: 12 tools.
- Public `route_mcp_tools` without auth: rejected with `Unauthorized`.
- Public `route_mcp_tools` with server-side API key: returns `owner_dev` with
  bounded `tool_count=18`.

## Rollback

Disable compact service:

```bash
systemctl --user disable --now ralfia-mcp-profile@chatgpt_compact.service
```

Remove Cloudflare ingress from `/home/rlopez/.cloudflared/opportunityops.yml`
and restart:

```bash
systemctl --user restart opportunityops-cloudflared.service
```
