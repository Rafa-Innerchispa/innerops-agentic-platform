# Judges start here — All Things Agentic 2026

**Purpose:** One honest entry point for hackathon reviewers. No fake PASS claims.

---

## Canonical URLs (use these)

| What | URL | Notes |
|------|-----|--------|
| **Judge Console** | https://inneros.creatorcore.ai/app/judge | Primary demo surface (1920×1080) |
| Login | https://inneros.creatorcore.ai/app/login | Password only — **do not use Google** |
| MCP status (optional) | http://192.168.1.5:8102/status | LAN; judges use public Judge UI instead |
| Legacy Cloud Run | https://inneros.pcdoctor.ai/app/judge | **Deprecated** — may show stale Operations Overview |

---

## Login (password only)

| Field | Value |
|-------|--------|
| Username | `HACKATHON-JUDGE` or `DEVPOST-JUDGE` |
| Password | `demo123` |
| After login | Navigate to `/app/judge` if not redirected automatically |

Source of truth in product code: `innerspark-workforce-ai/services/femar-mvp-core/src/lib/judgeCredentials.ts`.

---

## Layout at 1920×1080

1. **Top left:** ARIA composer (fixed pane, internal scroll — page should not jump on send).
2. **Top right:** Global Live Trace (persisted events; should not blank on empty poll).
3. **Center:** Seven independent **Run test** controls (one action each).
4. **Badges:** `READY` is neutral (not green). `RUNNING` / `PASS` / `PARTIAL` / `FAIL` only after real execution.

---

## Seven guided tests (independent)

Each button runs **one** backend action and should emit its own `correlation_id` in Global Live Trace.

| # | Label (UI) | Backend action | What it proves |
|---|------------|----------------|----------------|
| 1 | MCP health & safe trigger | `safe_trigger` | MCP health-watch + safe trigger |
| 2 | A2A bridge online | `a2a_handshake` | A2A online + agent card registry |
| 3 | FunctionGemma evidence | `gemma_probe` | Historical Gemma route; **current state may be NOT_RUNNING** |
| 4 | ISKCON emergency PDF | `iskcon_emergency_pdf` | Real PDF artifact (not a mock image) |
| 5 | ARIA judge workflow | `workflow_start` (ask_aria) | ARIA orchestrator via MCP |
| 6 | Local-first AMD routing | `workflow_start` (local_ai_task) | Local model routing (PARTIAL if GPU busy is OK) |
| 7 | RACB dispatch → AG-25 | `a2a_dispatch` (dry_run) | Durable ops dispatch without side effects |

Definitions: `innerspark-workforce-ai/.../src/lib/judgeDemoSteps.ts`.

---

## Truth states (do not misread)

| Topic | Expected honest state |
|-------|------------------------|
| **FunctionGemma** | HISTORICAL VERIFIED / CURRENTLY NOT_RUNNING / READY_TO_REDEPLOY — not “live fine-tuned Gemma” unless a fresh probe PASS says so |
| **MI325X cloud GPU** | HISTORICAL PROVEN / OWNER-APPROVED DESTROYED — preflight only in UI; no judge-triggered billing |
| **Gemini mandatory proof** | Gemini **3.5+** family (not 2.5 as compliance substitute) |
| **Trace** | Persisted backend events only — `inneros_judge_trace_contract_events.jsonl` on AMD `.5` + Mongo collections |

---

## 5-minute walkthrough (1080p recording)

1. Open https://inneros.creatorcore.ai/app/login → `HACKATHON-JUDGE` / `demo123`.
2. Confirm `/app/judge` loads with ARIA + Global Live Trace visible together.
3. Send ARIA: `hola` — expect contextual reply or explicit timeout/error (not endless canned fallback).
4. Run **Test 1** only — note `correlation_id` in trace; status should go RUNNING → PASS/PARTIAL/FAIL.
5. Run **Test 2** — confirm `a2a_status` online in trace/API.
6. Expand one test panel (if UX branch deployed) for “what this proves”.
7. Optional: Run **Test 7** — dry_run dispatch; trace should show RACB chain without mutating production.

---

## What this doc is not

- Not the **Band of Agents (BOA26)** demo — see `platform/services/swarm_os/docs/GUION_DEMO_JURADO.md` (legacy ngrok Band stack).
- Not a substitute for [`ALL_THINGS_AGENTIC.md`](ALL_THINGS_AGENTIC.md) requirement matrix.

---

## Related docs

- [`ALL_THINGS_AGENTIC.md`](ALL_THINGS_AGENTIC.md) — hackathon requirements → evidence map
- [`AGENTIC_DEFENSE.md`](AGENTIC_DEFENSE.md) — security / Model Armor mapping
- [`../coordination/HANDOFF_INNEROS_SPRINT_2026-08-29.md`](../coordination/HANDOFF_INNEROS_SPRINT_2026-08-29.md) — fleet URLs and demo accounts
