# MCP Router Gateway

MCP Router Gateway is the canonical small-surface entrypoint in front of the large InnerOS MCP ecosystem.

It is not another one-off profile server. It is a session-aware MCP gateway that:

- accepts MCP `streamable-http` JSON-RPC requests;
- creates a proxy `Mcp-Session-Id` for the client;
- maintains separate backend sessions per upstream MCP server;
- intercepts `tools/list` and exposes only the active profile;
- annotates every exposed tool with its selected backend;
- validates `tools/call` against the active profile;
- routes allowed calls to the correct backend;
- fails closed with `ToolNotAllowedError` when a tool is not in profile;
- supports multiple short MCPs such as InnerOS compact, quoteops, GitLab and Docker/infra.

## Why This Exists

The full InnerOS MCP can expose hundreds of tools. That is useful for admin work, but it poisons small-context clients and can kill ChatGPT sessions. Clients should connect to one router URL and receive a short task-specific surface.

Recommended public shape:

```text
https://mcp.pcdoctor.ai/router/mcp
```

The router then decides internally:

```text
chatgpt_compact -> inneros_compact
quoteops        -> quoteops
coding          -> inneros_compact + infra_docker when enabled
gitlab          -> mcp-gitlab when enabled
infra_docker    -> mcp-infra-docker when enabled
admin           -> full inneros_core, explicitly only
```

## Local Run

```bash
MCP_ROUTER_HOST=127.0.0.1 \
MCP_ROUTER_PORT=8250 \
MCP_ROUTER_PROFILE=chatgpt_compact \
MCP_ROUTER_PROFILES=profiles.json \
PYTHONPATH=src python -m mcp_router_gateway.server
```

Health:

```bash
curl http://127.0.0.1:8250/health
```

## MCP Session Probe

Initialize:

```bash
curl -i http://127.0.0.1:8250 \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"probe","version":"1"}}}'
```

Then call `tools/list` with the returned `Mcp-Session-Id`.

## Profiles

Profiles live in `profiles.json`.

- `chatgpt_compact`: default. 15 coordination and bootstrap tools.
- `quoteops`: commercial quote tools.
- `coding`: source/git/fs/docker shape; uses short micro-MCPs when enabled.
- `gitlab`: reserved for the GitLab micro-MCP.
- `infra_docker`: reserved for Docker/infra tools.
- `admin`: full InnerOS core MCP, not for default ChatGPT sessions.

Backends with `"enabled": false` are not used. A profile that points only at disabled backends will fail closed instead of silently falling back to the full MCP.

## Security

Production uses the same OAuth entrypoint as the canonical MCP:

```text
Resource: https://mcp.pcdoctor.ai/mcp
Authorization server: https://auth.pcdoctor.ai
Router endpoint: https://mcp.pcdoctor.ai/router/mcp
```

`MCP_ROUTER_AUTH_MODE=oauth_passthrough` accepts `Authorization: Bearer ...` and forwards it to the selected backend MCP. The backend remains responsible for token/scopes validation, so the router does not become a second identity system.

`MCP_ROUTER_BEARER_TOKEN` is only a private break-glass guard for trusted local operation. Do not configure ChatGPT or public agents to use it.

Unauthorized tools return:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "error": {
    "code": -32060,
    "message": "ToolNotAllowedError"
  }
}
```

## Docker

```bash
docker build -t mcp-router-gateway .
docker run --rm -p 8250:8250 \
  -e MCP_ROUTER_PROFILE=chatgpt_compact \
  -e MCP_ROUTER_PROFILES=/app/profiles.json \
  mcp-router-gateway
```

## Selftest Without Pytest

```bash
PYTHONPATH=src python selftest.py
```
