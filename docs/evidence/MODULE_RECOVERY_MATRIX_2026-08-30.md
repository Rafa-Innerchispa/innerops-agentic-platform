# MODULE_RECOVERY_MATRIX - 2026-08-30

Scope: `ops_9e2ad692578a` / `inneros-module-recovery-verification-20260830`.

Rules honored: no Cursor UI edits, no production deploy/restart, no `workforce.pcdoctor.ai` validation or changes. New-domain/canonical paths only.

## Canonical module matrix

| Module / vertical | Canonical path found | Service / URL evidence | Store / data evidence | Auth / tenant evidence | Verification run | State | Notes / risks |
|---|---|---|---|---|---|---|---|
| InnerOS A2A Gateway | `/home/rlopez/inneros/inneros_core/modules/a2a-gateway`; runtime in `/platform/inneros_core_runtime/a2a_*` | `ralfia-mcp.service` active on `:8102`; `a2a_status` OK; 58 agents | Mongo `ralfia_ops_tasks`, `ralfia_a2a_tasks` | RACB locks/tasks; MCP auth layer | `a2a_status`, `a2a_agent_cards` PASS | LIVE | ChatGPT connector OAuth may still need client-side reauth; server runtime is OK. |
| Workforce / InnerSpark Workforce AI | `/home/rlopez/inneros/inneros_core/workspaces/innerspark-workforce-ai/services/femar-mvp-core` | `femar-mvp-core.service` active on `:3010`; new-domain checks use `inneros.creatorcore.ai` / `workforce.creatorcore.ai` | Firestore `users`, `employees`, `mail`; local package | `requireModuleAccess`, `assertTenantAccess`, Google OAuth | `npm ci` PASS, Jest 20 tests PASS on branch, `npm run build` PASS | LIVE/PARTIAL | Live OAuth status still shows localhost until branch `codex/oauth-rbac-security-20260830` is integrated and restarted/deployed. Do not use `workforce.pcdoctor.ai`. |
| VigilOS / Visitors | `/home/rlopez/inneros/inneros_core/modules/visitors` | `vigilos-cursor.service` backend `:8011` 200 `/health`; `vigilos-cursor-frontend.service` `:5175` 200 | Local backend DB mode plus sync remote shown by `/health`; frontend Vite | Auth not fully proven for public execution surfaces | Frontend `npm run build` PASS; backend `/health` 200 | LIVE/PARTIAL | Needs authenticated 403 probes before enabling non-read-only tools. |
| QuoteOps | `/home/rlopez/inneros/inneros_core/modules/quoteops` | `ralfia-quoteops.service` active; local probe `:2026` 200 HTML | QuoteOps data/docs, Mongo ops quote flows through MCP | MCP/RACB controlled quote tools | HTTP probe 200; pytest BLOCKED because `.venv` lacks pytest | LIVE/PARTIAL | Migration debt: `.venv` symlink points to `/home/rlopez/projects/ralphiia-quoteops/.venv`; do not change hot while service is live. |
| Smart Quoter | `/home/rlopez/inneros/inneros_core/modules/smart-quoter` | `ralfia-smart-quoter.service` active on `:2026`/service config; local 200 seen on quoter surface | Catalog/quote runtime | MCP quoter profile | HTTP probe 200 | LIVE | Needs route/auth review before public write exposure. |
| FounderOS | `/home/rlopez/inneros/inneros_core/modules/founderos` | `ralfia-founderos.service` active on `:8766`; local 200 HTML | Module docs/evidence and remote dev API files | Entitlement `founderos`; backend 403 not fully proven | HTTP probe 200; pytest BLOCKED because pytest not installed | LIVE/PARTIAL | Looks derived from QuoteOps/FounderOS hackathon stack; needs dependency env rebuilt under core. |
| ISKCON Desk | `/home/rlopez/inneros/inneros_core/modules/iskcon-desk` | `iskcon-desk.service` active on `:2027`; local 200 HTML | Module-local sponsor desk; ISKCON docs/memory | Workforce entitlements default `iskcon-desk`; demo users explicit modules | HTTP probe 200 | LIVE/PARTIAL | WhatsApp scheduled content still needs approval workflow/group IDs; authenticated 403 probes pending. |
| Credentials | No standalone module directory found; appears as module id/route references in Workforce/platform | No standalone service found | Credential vault/runtime exists in platform (`owner_vault`, auth middleware, browser broker) | Entitlement id `credentials` | Static discovery only | PARTIAL | Needs canonical module owner/path before exposing as product surface. |
| FieldSpark / Photography | No standalone repo/module found outside historical references. Present as `fieldspark-photography` entitlement and Workforce ecosystem metadata. | No standalone service found; Workforce contains feature references and device gateway photo capture references | Workforce/mock/mobile/photo references; no independent store proven | Entitlement only; PC Doctor all-authorized, IA PRO/FEMAR blocked by tests unless explicit grant | Static discovery; no buildable standalone module located | PARTIAL/RECOVERABLE | Priority finding: do not reconstruct from notes; real code appears embedded in Workforce/hackathon artifacts, not a canonical module yet. Needs extraction/provisioning decision. |
| MSP/CRM/field ops/accounting/AP/AR/inventory | Tenant configs under `/tenants`, platform ops stores/tools | MCP/portal/ops tools active | Mongo namespaces `ops_clients`, `ops_sites`, `contifico_*`, `accounting_*`; tenant YAML | Tenant configs exist; per-route backend 403 not fully proven | Static config evidence | RECOVERABLE | Needs endpoint-by-endpoint auth matrix before client exposure. |
| Hackathon reusable flows | `/platform/scripts/*hackathon*`, ACP scripts, module docs/evidence | MCP/local worker flows | Mongo ops/evidence and repo worktrees | RACB/worktrees/locks | Static discovery | RECOVERABLE | Keep demos read-only; gate execution via OAuth/Access/approval. |

## FieldSpark / Photography conclusion

No independent canonical `fieldspark` or `photography` module/repo was found under active core roots after excluding local models, venvs, node_modules, dist/build, and worktree noise. The recoverable implementation appears to be metadata and feature-level code inside Workforce plus historical hackathon traces. Recommended next step is to create a formal extraction/provisioning task only after Rafael decides whether FieldSpark should become a sellable standalone module or remain a Workforce feature.

## Verification summary

- Visitors frontend: `npm run build` PASS.
- Visitors backend: `http://127.0.0.1:8011/health` => 200 JSON.
- ISKCON Desk: `http://127.0.0.1:2027/` => 200 HTML.
- FounderOS: `http://127.0.0.1:8766/` => 200 HTML; pytest blocked by missing pytest.
- QuoteOps/Smart Quoter surface: `http://127.0.0.1:2026/` => 200 HTML; QuoteOps pytest blocked because `.venv` points to old `/home/rlopez/projects/ralphiia-quoteops/.venv` and lacks pytest.
- Workforce branch `codex/oauth-rbac-security-20260830`: `npm ci` PASS, 20 Jest tests PASS, build PASS.

## Open follow-ups

1. Rebuild QuoteOps/FounderOS Python envs inside `/home/rlopez/inneros/inneros_core/modules/*/.venv` instead of depending on `/home/rlopez/projects` symlinks.
2. Decide whether FieldSpark/Photography is standalone product/module or Workforce feature; then create canonical module path and tests.
3. Add authenticated route probes for Visitors, FounderOS, Credentials, FieldSpark, ISKCON before exposing non-read-only public surfaces.
4. Keep `workforce.pcdoctor.ai` historical/no-touch unless Rafael explicitly reactivates it.
