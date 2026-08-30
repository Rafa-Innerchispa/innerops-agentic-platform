# InnerOS module, RBAC, OAuth security audit - 2026-08-30

## Scope

Source request: `ops_a41890530655`, correlation `inneros-module-audit-rbac-a2a-20260830`, plus message `msg_f1af7600fa43cbb1` for OAuth/SMTP/tenant security review.

Restrictions honored: no InnerOSShell/UX changes, no `workforce.pcdoctor.ai` deployment, no production restart. Product fix was prepared in an isolated Workforce branch for ChatGPTA/Cursor integration.

## Live runtime evidence

- Coordination revision read/acked by Codex: `8691`.
- A2A canonical runtime: `a2a_status.ok=True`, `agent_count=58`, `root_orchestrator=AG-25`.
- `a2a_agent_cards.ok=True`, `cards_count=58`; module import now resolves from `inneros_core_runtime/a2a_agent_registry.py` through the `raphiia_openai` compatibility path.
- Public read-only checks:
  - `https://inneros.creatorcore.ai/api/ecosystem/health` => 200 JSON.
  - `https://inneros.creatorcore.ai/api/ecosystem/modules` => 401 JSON without session.
  - `https://inneros.creatorcore.ai/api/ecosystem/modules/quoteops/access` => 401 JSON without session.
  - `https://inneros.creatorcore.ai/api/employees` => 401 JSON without session.
  - `https://inneros.pcdoctor.ai/` => 200 HTML.
  - `https://inneros.iskconguayaquil.org/app/login` => 200 HTML.

## Module inventory

| Vertical/module | Repo/path found | Data/store | Service/url evidence | Auth/RBAC evidence | State | Risks/actions |
|---|---|---|---|---|---|---|
| Workforce | `/home/rlopez/inneros/inneros_core/workspaces/innerspark-workforce-ai/services/femar-mvp-core` | Firestore `users`, `employees`, `mail`; app-local config | `femar-mvp-core.service` active on `:3010`; `inneros.creatorcore.ai` APIs respond | Session cookie + `requireModuleAccess('workforce-ai')`; backend APIs return 401 without session | LIVE/PARTIAL | Live OAuth redirect still shows `localhost:3010` until branch `codex/oauth-rbac-security-20260830` is integrated/restarted. |
| VigilOS / Visitors | `/home/rlopez/inneros/inneros_core/modules/visitors` plus `vigilos-cursor.service` and `vigilos-cursor-frontend.service` | Module-local/backend store not fully audited in this pass | Backend `:8011`, frontend `:5175`, public `visitors.creatorcore.ai` previously 200 | Do not assume tenant isolation; needs module-specific auth probe | RECOVERABLE/LIVE | Security posture must be confirmed before exposing command/write surfaces. |
| Credentials | Module id exists in Workforce entitlements; no standalone module dir found in `modules/` | Unknown | No standalone service found | Entitlement only | PARTIAL | Needs source-of-truth path/store before production use. |
| QuoteOps | `/home/rlopez/inneros/inneros_core/modules/quoteops`; platform QuoteOps tools present | Mongo `ops_quotes`, catalog/offer collections through MCP | `ralfia-quoteops.service` active | MCP/RACB tools; tenant configs include quoting namespaces | LIVE | Old module symlink/deletion noise remains in dirty platform checkout; preserve core path. |
| Smart Quoter | `/home/rlopez/inneros/inneros_core/modules/smart-quoter`; config/service | Mongo quote/order flow | `ralfia-smart-quoter.service` active on `:2026` | MCP/tool-profile guarded flow | LIVE | Confirm public ingress auth before broad exposure. |
| FounderOS | `/home/rlopez/inneros/inneros_core/modules/founderos` | Module-local, not fully audited | `ralfia-founderos.service` active on `:8766` | Entitlement id `founderos` | RECOVERABLE/LIVE | Needs backend 403 probe. |
| FieldSpark / photography | Entitlement id `fieldspark-photography`; likely hackathon/product workspace | Unknown in this pass | No active service seen by name | Entitlement only for `innerspark_labs`/PC Doctor all-authorized | PARTIAL | Needs repo/path recovery map before public claims. |
| MSP/CRM/field ops/accounting/AP/AR/inventory | Tenant configs: `pcdoctor` namespaces `ops_clients`, `ops_sites`, `contifico_*`, `accounting_*`; module dirs not all explicit | Mongo `pcdoctor_swarm`, Contifico archives | MCP ops tools and portal active | Tenant YAML scopes namespaces; app-level RBAC mixed | RECOVERABLE | Need backend enforcement tests per API before enabling client users. |
| ISKCON | `/home/rlopez/inneros/inneros_core/modules/iskcon-desk`; companies/tenant metadata | ISKCON memory/docs, module store not fully audited | `iskcon-desk.service` active on `:2027`; `inneros.iskconguayaquil.org/app/login` 200 | Entitlement default `iskcon-desk`; demo users explicit modules | LIVE/PARTIAL | Need WhatsApp approval workflow and group/channel ids before scheduled sends. |
| A2A Gateway | `/home/rlopez/inneros/inneros_core/modules/a2a-gateway`; platform bridge | Mongo `ralfia_a2a_tasks`, `ralfia_ops_tasks` | `ralfia-mcp.service` active on `:8102` | RACB/locks/tasks | LIVE | ChatGPT MCP OAuth connector may still need client-side reauth; server runtime itself is OK. |
| Hackathon reusable flows | `scripts/google_hackathon_e2e_bundle.py`, `scripts/acp_*`, portfolio sync, dev swarm | Mongo tasks/evidence, repo worktrees | MCP + local workers, Cloud Run/domain tools | RACB/locks/worktrees | RECOVERABLE | Keep demos read-only unless OAuth/Access gates execution surfaces. |

## RBAC contract

Required contract confirmed/implemented as branch-ready fix:

- Membership is tenant/company scoped (`companyId`).
- Role alone is not enough; module entitlement must be enforced by backend API (`requireModuleAccess`, `assertModuleAccess`) and not only by hidden nav.
- PC Doctor admin/superadmin is all-authorized for InnerOS modules.
- FEMAR and IA PRO are Workforce-only, including if role string says `superadmin`.
- Hackathon defaults to minimal `workforce-ai`, unless explicit demo modules are granted.
- Unauthenticated API probes return 401; cross-tenant routes use `assertTenantAccess` for Workforce employees/schedules.

Fix branch prepared in Workforce repo:

- Branch: `codex/oauth-rbac-security-20260830`
- Commit: `61a2ff74d3e06a6697cdd6365ad3ccd306e69028`
- Changes: forwarded-header-aware Google OAuth origin, secure cookie decisions based on public origin, RBAC regression where FEMAR/IA PRO no longer inherit all modules via `superadmin`.

## OAuth and SMTP review

Findings:

- `platform/.env` is not tracked, but mode is `664`; recommended hardening is `chmod 600 /home/rlopez/inneros/inneros_core/platform/.env` during maintenance window.
- Workforce package has `.gitignore` env coverage and no tracked `.env` entries.
- OAuth callback does not auto-approve arbitrary Google users. Existing users with `REJECTED`/`PENDING` are blocked; new auto-approval uses `INNEROS_OAUTH_AUTO_APPROVE_EMAILS` allowlist, defaulting only to Rafael admin email.
- Live auth status currently reports `https://localhost:3010/api/auth/google/callback` for public host checks; fixed in isolated branch but not deployed/restarted.
- `mailDelivery` queues Firestore Trigger Email and also sends SMTP when configured. This is intentional dual-delivery/fallback behavior, but it can duplicate emails if both channels are active. Recommended next step: add environment flag or delivery mode enum before production notification scale-up.
- `mailDeliveryStatus()` exposes SMTP host/from but not SMTP password. Keep as admin-only or internal-only endpoint.

## Tests and commands

Workforce isolated branch `codex/oauth-rbac-security-20260830`:

- `npm ci` inside nested package root `services/femar-mvp-core`: PASS; audited 891 packages; npm reported 8 vulnerabilities (6 moderate, 2 high) for dependency review.
- `npm test -- src/lib/entityEntitlements.test.ts --runInBand`: PASS, 11 tests.
- `npm run build`: PASS; Next.js build completed. Warnings remain: multiple lockfiles workspace-root inference and deprecated middleware convention.

Canonical live/source checks:

- A2A status/cards: PASS, 58 agents.
- Unauthenticated public API access: 401 where expected for protected module/employee APIs.

## Remaining blockers / next actions

1. Integrate or cherry-pick Workforce commit `61a2ff74d3e06a6697cdd6365ad3ccd306e69028`, then perform controlled restart/deploy of `femar-mvp-core.service` / target Cloud Run only when ChatGPTA is ready. Current live public auth status still shows localhost because production was not restarted/deployed by this task.
2. Fix canonical metadata drift: `config/products/workforce-ai.yaml` and `config/REPO_REGISTRY.yaml` still reference `/home/rlopez/projects/innerspark-workforce-ai`; canonical runtime is `/home/rlopez/inneros/inneros_core/workspaces/innerspark-workforce-ai`.
3. Harden `platform/.env` file mode from `664` to `600`.
4. Decide `mailDelivery` policy: queue-only, smtp-only, or dual-with-idempotency to avoid duplicate admin emails.
5. Run module-specific authenticated 403 tests for Visitors, FounderOS, Credentials, FieldSpark, and ISKCON before exposing non-read-only surfaces.
