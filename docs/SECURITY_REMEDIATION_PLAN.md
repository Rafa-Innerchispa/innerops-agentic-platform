# Repository security remediation plan (2026-08-30)

Scope: **current-tree cleanup only**. No force-push or history rewrite in this phase.

## Incident context

GitGuardian flagged multiple exposures tied to pre-change snapshots and runtime
secret files committed under `innerops-agentic-platform`. Commit `f031285` (branch
`codex/disk-steward-tools-20260830`) already removed tracked `backups/**` snapshots
from that line; `main` and several feature branches still carry sensitive paths.

## REDACTED affected-file matrix (current-tree)

| Secret class | Path pattern | Action in this PR |
|---|---|---|
| Full `.env` dump | `backups/*-pre-*.env` | Untrack; keep `*.example` |
| WhatsApp webhook verify token | `platform/data/whatsapp_webhook_secret` | Untrack; `*.example` + gitignore |
| Wi-Fi PSK JSON | `var/peer_wifi_credentials/*.json` | Untrack; README only |
| MCP / IDE local config | `.cursor/mcp.json` | Root gitignore |
| Pre-change Python snapshots | `backups/**` (119 files) | Untrack entire tree |

Deploy templates `platform/deploy/env/*.node.env` remain tracked: they contain
localhost Mongo URIs without credentials.

## History remediation (phase 2 — Codex `ops_839d45f95780`)

1. Inventory refs: `main`, `cursor/*`, `codex/*`, tags touching `backups/` or secret paths.
2. Prefer `git filter-repo` with `--path` deletes for:
   - `backups/`
   - `platform/data/whatsapp_webhook_secret`
   - `var/peer_wifi_credentials/`
3. Coordinate credential rotation (Antigravity `ops_cf5f1d370e21`) **before** purge push.
4. Force-push only after Rafael approval + collaborator freeze window.

## Guardrails added

- Root `.gitignore` blocks backups, local MCP config, webhook secret, Wi-Fi JSON.
- `scripts/check-tracked-secrets.sh` — run in CI/pre-commit on `git ls-files`.
- `platform/.gitignore` already ignores `platform/.env` and `platform/.cursor/mcp.json`.

## Verification

```bash
bash scripts/check-tracked-secrets.sh
git ls-files backups/ platform/data/whatsapp_webhook_secret var/peer_wifi_credentials/
# expect: only README / *.example under backups/
```
