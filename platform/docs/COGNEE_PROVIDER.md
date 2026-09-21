# Cognee Provider / Standalone MCP

Cognee is a reusable InnerOS platform capability. It is not owned by any
hackathon project.

## Surfaces

- Provider module: `raphiia_openai.cognee_provider`
- Standalone MCP: `raphiia_openai.cognee_mcp:mcp`
- Capabilities:
  - `cognee_status`
  - `cognee_preflight`
  - `cognee_memory_search`
  - `cognee_remember`
  - `cognee_knowledge_graph`

## Runtime configuration

Secrets are never committed. The runtime projects these values server-side:

- `COGNEE_SERVICE_URL`
- `COGNEE_API_KEY`
- `COGNEE_DATASET` (optional)

The same provider can point at Cognee Cloud or a self-hosted Cognee service.

## Consumer rule

Products request the `memory_graph` capability through Resource Fabric or
connect to the standalone MCP. They must not reimplement Cognee credentials or
provider logic inside product repositories.

## Hackathon use

`inneros-personal-brain` is a consumer. The provider remains available after
the hackathon for future projects and external MCP clients.
