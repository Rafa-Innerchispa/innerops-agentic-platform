# InnerOS MCP Router

Shadow-only MCP proxy in front of the canonical monolith on port 8102.

## Guarantees

- Keeps the monolith unchanged and independently runnable.
- Exposes bounded server-assigned profiles: minimal <=15, coding <=25.
- Uses canonical `mcp_profiles`, `capability_router`, scopes and risk filtering.
- Never trusts a client-provided profile to elevate privileges.
- Admin profile is disabled unless server policy, identity and `ralfia:admin` all agree.
- Fetches live backend `tools/list` schemas and pins the catalog fingerprint.
- Validates tool arguments against the live input schema before forwarding.
- Applies path, command, rate and concurrency deny layers.
- Does not fabricate initialize/health success when the backend is unavailable.
- Federation candidates remain disabled until parity is independently verified.

## Shadow deployment

Port 8103 is currently occupied by SSO, so the example service overrides the router to 8113.
The router requires an identities file containing SHA-256 hashes of complete Authorization
headers mapped to server-assigned profiles/scopes. Tokens themselves are never stored there.

Production clients must not be repointed until the authenticated live MCP E2E passes.
