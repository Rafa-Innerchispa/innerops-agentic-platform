# Notion Truth / Recovery Audit — 2026-09-08

## Scope

Task `ops_27b3829cb306`, correlation `notion-inneros-truth-recovery-audit-20260907`.
This audit treats Mongo + Git + InnerOS runtime as canonical operational truth and Notion as a searchable knowledge and recovery plane, not the only source of truth.

## Evidence Matrix

| Flow | Status | Evidence |
| --- | --- | --- |
| Notion native connector identity | PROVEN | Workspace `Pc Doctor S.A.’s Workspace`; user `InnerSpark` / `rlopez@innerchispa.us`; all Notion tools available. |
| RalfIA Notion API bridge | PROVEN | `get_notion_status`: configured=true, connected=true, bot_id present, docs DB `39acb2de-eb0f-8195-b465-de988420fc6b`. |
| RalfIA Coordination contract | PROVEN | `get_notion_coordination_contract`: DB `RalfIA Coordination`, response contract Mongo `ralfia_ops_tasks` + `ralfia_notion_coordination_index`. |
| Server -> Notion sync history | PROVEN | `get_notion_sync_log`: recent successful creates/updates for Audit Fabric execution matrix, implementation handoff, central map, Qwoted playbook. |
| Server -> Notion sync preview | PROVEN | `preview_notion_sync` and `sync_documentation_now(mode=dry_run)` returned update/skip plans without errors. |
| Document Vault | PROVEN | Root `/mnt/datos_agentes/document_vault` exists, writable, Mongo OK, peer roots exist on Intel and AMD. |
| Notion -> InnerOS webhook | PROVEN_SYNTHETIC | Webhook URL and watched DBs exist. Branch fixes signature verification to use the stored Mongo pending token when env is absent. Runtime smoke reports `verification_token_available=true`, source `mongo_pending`, and a signed synthetic event verifies successfully. |
| Local hybrid search vs Notion AI | PARTIAL | Notion AI finds historical pages for `notion_prod_v3`, `index_notion_v2.py`, `sync_documents_catalog.py`, and Conversation Memory. Runtime `hybrid_search` returned noisy/irrelevant memory hits for some exact historical queries. |
| Hybrid search recovery fix | PROVEN_BRANCH | Branch adds Notion API fallback only when Qdrant returns no hits, preserving local Qdrant as primary path. Unit tests pass, and runtime-venv smoke now returns Notion API results first for Conversation Memory queries. |

## Root Cause

Notion AI searches the live Notion workspace directly and sees pages that are not necessarily represented well in the local Qdrant/Mongo ranking layer. InnerOS local search had a healthy Qdrant collection (`inneros_kb`, 99,011 points) but `hybrid_search` did not surface Notion results when Qdrant returned no usable hits, so local agents could miss documents that Notion could find. Worktrees also did not load the central runtime `.env`, so isolated tests could not use the configured Notion bridge without copying secrets.

A separate environment hygiene gap remains: the live runtime still reports `NOTION_WEBHOOK_VERIFICATION_TOKEN` absent from `.env`, but the branch safely verifies signatures from the stored Mongo pending token. This is acceptable for continuity, while the cleaner final state is to persist the token in runtime env and keep Mongo as recovery copy.

## Safe Fix

`hybrid_search` now keeps Mongo memory, Qdrant, doc vault and ops search, but adds a guarded `notion_api` fallback only when Qdrant returns no hits. `settings.py` now loads `INNEROS_RUNTIME_ENV`, local `platform/.env`, then the central `/home/rlopez/inneros/inneros_core/platform/.env` with `override=False`, so worktrees can use configured runtime integrations without copying secrets. This helps ChatGPT, voice and local agents find current Notion truth without replacing the local index.

## Remaining Closure Criteria

1. Promote this branch into the live MCP runtime during the controlled promotion window.
2. Save the Notion webhook verification token in the live runtime env as the long-term clean source, leaving Mongo pending token as recovery fallback.
3. Run a real Notion UI edit/comment event after promotion and prove Mongo dedupe in `ralfia_notion_webhook_dedupe`.
3. Run one controlled `sync_documentation_now(mode=apply, limit=N)` only for selected docs after reviewing dry-run updates.
4. Reindex stale Notion exports into Qdrant/Postgres if local search still diverges after the API fallback.
5. Keep this as recovery-plane evidence, not as proof that Notion is the only operational truth.
