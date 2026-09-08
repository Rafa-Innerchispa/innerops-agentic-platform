# Notion MCP Short Auth

Purpose: let a Notion Custom Agent connect to InnerOS MCP Short without giving it the global owner/admin MCP key.

## Notion fields

- URL: `https://mcp-chatgpt.creatorcore.ai/mcp`
- Auth method: API key / custom header
- Header name: `X-API-Key`
- Secret value: owner-only; never paste it into Mongo coordination, Notion docs, Git, logs, or agent messages.

## Runtime policy

The key for `notion.claude` must be a scoped MCP API key, not `MCP_API_KEY`.

Recommended hash-only record shape for `ralfia_mcp_scoped_api_keys`:

```json
{
  "identity": "notion.claude",
  "key_hash": "sha256:<64 lowercase hex chars>",
  "scopes": ["ralfia:read"],
  "allowed_profiles": ["chatgpt_compact", "notion_mcp_short"],
  "allowed_tools": [
    "mcp_version",
    "diagnose_mcp_session",
    "list_mcp_tool_profiles",
    "get_mcp_profile",
    "route_mcp_tools",
    "bootstrap_context",
    "get_coordination_live",
    "get_notion_status",
    "search_notion_pages",
    "get_notion_coordination_contract",
    "get_notion_sync_log",
    "get_notion_webhook_setup"
  ],
  "tenant_id": "inneros",
  "status": "active",
  "purpose": "Notion Custom Agent read-only InnerOS MCP Short bridge"
}
```

The raw key may be stored in Owner Vault for owner retrieval, but runtime validation uses only the hash. If the key must gain write access later, add the smallest exact tool list and scope required for that test; do not add `ralfia:admin`, `ralfia:private_memory`, owner-vault tools, or cloud/provider ops.

## Verification

1. Call MCP Short with `X-API-Key` and `mcp_version`.
2. Call `get_mcp_profile` for `notion_mcp_short` or `list_mcp_tool_profiles` and confirm the profile exists.
3. Call a read-only Notion probe such as `get_notion_status` or `search_notion_pages`.
4. Confirm write tools such as `notion_push_doc` and admin/private tools are denied for the same key.

OAuth remains the preferred long-term route where the client UX supports it; scoped API keys are the least-privilege fallback for clients that cannot complete OAuth/DCR cleanly.
