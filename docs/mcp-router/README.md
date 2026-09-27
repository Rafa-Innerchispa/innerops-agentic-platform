# MCP Router & Tool Throttling Gateway

Canonical InnerOS subproject for reducing MCP tool exposure, enforcing profile-based access, and preparing federated micro-MCP backends.

## Canonical references
- Repository: `Rafa-Innerchispa/innerops-agentic-platform`
- Ops task: `ops_68ac0309e069`
- Correlation: `inneros-mcp-router-tool-throttling-20260927`
- Development branch: `antigravity/mcp-router-20260927`
- Detailed migration handoff: `docs/mcp-router/HANDOFF_20260927.md`

## Runtime architecture
- Existing monolithic MCP remains operational on port `8102`.
- New router is developed on configurable port `8103` in shadow mode.
- The router reuses canonical InnerOS MCP profiles and capability policy.
- Production client cutover is outside the initial shadow implementation and requires independent verification.

## Initial deliverables
- MCP protocol proxy: initialize, ping, tools/list, tools/call.
- profile_minimal <= 15 tools.
- profile_coding <= 25 tools.
- profile_admin disabled by default and server-authorized.
- Tool deny/throttle without MCP session termination.
- Catalog caching/fingerprinting.
- Filesystem/terminal deny layer.
- Structured metrics.
- GitLab/Docker federation scaffolding behind disabled feature flags.
- Direct-vs-router latency and context-size benchmarks.
- Rollback/runbook.

## Acceptance evidence
Store generated acceptance evidence under:

`platform/docs/acceptance/ops_68ac0309e069/`

The implementation is not considered complete until the shadow router has passed protocol, security, throttling, catalog, latency, and rollback tests and has been independently verified.
