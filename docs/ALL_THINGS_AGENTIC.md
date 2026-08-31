# All Things Agentic — submission scope & evidence checklist

**Hackathon:** Google All Things Agentic 2026  
**Product:** InnerOS / ARIA Enterprise Agent Fleet  
**Devpost:** https://devpost.com/software/innerops-aria-enterprise-agent-fleet  
**Judge entry:** [`JUDGES_START_HERE.md`](JUDGES_START_HERE.md)

This document maps **official themes** to **observable evidence**. Status labels are honest: `VERIFIED`, `PARTIAL`, `NOT_RUNNING`, `PLANNED`.

---

## What we are submitting

InnerOS is an **operating layer** for a real small technology company: signals → memory → delegation → bounded execution → verification → recovery → evidence.

The hackathon acceleration (Aug 2026) added:

- Multi-agent orchestration with durable RACB ops tasks
- IDE Task Bridge + A2A (58+ agent cards)
- Judge Console for independent verification
- Local-first routing (AMD `.5` + Intel `.4`)
- Google Cloud path (Cloud Run, Firestore, Gemini) with explicit local-first fallback

Pre-existing foundations (Workforce, MCP, Mongo ops) are disclosed in root [`README.md`](../README.md) — not claimed as invented during the submission window.

---

## Requirement → evidence matrix

| Requirement | Where to verify | Status | Notes |
|-------------|-----------------|--------|-------|
| **Gemini 3.5+** | Judge Test 5/6 + Resource Fabric selector; Vertex status MCP | PARTIAL | Quota/hackathon credits may block live Vertex; UI must not claim LIVE without probe |
| **Google ADK / google-genai** | `platform/inneros_core_runtime/google_adk_a2a.py`; RemoteA2aAgent contract tests | VERIFIED | NON-LIVE contract + A2A bridge reuse |
| **Cloud Run** | GCP project `innerops-agentic-platform`; legacy `inneros.pcdoctor.ai` | PARTIAL | Canonical **demo** moved to `inneros.creatorcore.ai` on AMD `.5` |
| **Firestore** | Workforce / Judge sessions; composite index gaps documented | PARTIAL | Some ARIA session queries need index or code fallback |
| **Pub/Sub** | Platform integrations where async events used | PARTIAL | Not every flow uses Pub/Sub — only where listed in ops evidence |
| **Agent Registry** | MCP `a2a_agent_cards()` ≈ 58 cards; Test 2 handshake | VERIFIED | Live bridge `a2a-inneros-1.0` |
| **Agent Runtime** | Dev Swarm + local_exec + IDE bridge | VERIFIED | Scheduler truth fix branch `cursor/scheduler-truth-fix-20260831` |
| **Memory Bank** | Mongo coordination + agent messages + INBOX.md | VERIFIED | Canonical bus, not prompt-only memory |
| **Agent Identity** | `identify_agent_session`, agent cards metadata | VERIFIED | Per-agent mailboxes |
| **Agent Gateway** | MCP `:8102`, portal `:8101` | VERIFIED | LAN + Cloudflare tunnel to creatorcore |
| **Model Armor / agentic defense** | [`AGENTIC_DEFENSE.md`](AGENTIC_DEFENSE.md) | PARTIAL | Mapped; full Google-side capture varies by quota |
| **FunctionGemma (bonus)** | Judge Test 3 `gemma_probe` | PARTIAL | Historical proof; **currently NOT_RUNNING** is valid |
| **Local AMD (Qwen/vLLM)** | Judge Test 6; Ollama on `.5` | VERIFIED/PARTIAL | PARTIAL when GPU busy or model unloaded |
| **A2A + MCP trace** | Judge Test 7 dry_run dispatch; Global Live Trace | VERIFIED | Persisted trace contract on `:3010` |
| **Independent judge UI** | https://inneros.creatorcore.ai/app/judge | VERIFIED | See [`JUDGES_START_HERE.md`](JUDGES_START_HERE.md) |

---

## Repositories (roles)

| Repo | Role |
|------|------|
| `Rafa-Innerchispa/innerops-agentic-platform` | Control plane, MCP, scheduler, docs |
| `Rafa-Innerchispa/innerspark-workforce-ai` | Judge Console UI + `/api/ecosystem/judge` |
| `inneros_core/platform` (deployed runtime) | Live MCP `:8102`, editorial `:8101/editorial` |

See [`PRODUCT_VS_HACKATHON.md`](PRODUCT_VS_HACKATHON.md) for product vs hackathon boundaries.

---

## Demo URLs (canonical vs legacy)

| URL | Role |
|-----|------|
| https://inneros.creatorcore.ai/app/judge | **Primary judge demo** |
| https://inneros.creatorcore.ai/app/login | Judge login |
| https://workforce.creatorcore.ai/ | Workforce product (separate from Judge) |
| https://inneros.pcdoctor.ai/ | Legacy Cloud Run — do not use for PASS |
| http://127.0.0.1:8101/editorial | Editorial hub (internal/LAN) |

---

## Regression tests (platform)

From repo root with platform venv:

```bash
cd platform
python3 -m unittest \
  tests.test_scheduler_task_contract \
  tests.test_anti_freeze_scheduler \
  tests.test_dev_swarm_repo_inference \
  tests.test_google_adk_a2a_nonlive
```

Judge product tests live in `innerspark-workforce-ai/services/femar-mvp-core` (npm test).

---

## Known gaps (honest)

1. **`docs/ALL_THINGS_AGENTIC.md`** — this file; keep updated as evidence moves.
2. **BOA26 judge scripts** in `platform/services/swarm_os/docs/GUION_DEMO_JURADO.md` — different hackathon; pointer added in [`JUDGES_START_HERE.md`](JUDGES_START_HERE.md).
3. **Cloud Run vs AMD cutover** — submission narrative must say creatorcore is canonical for Judge live demo.
4. **Antigravity UX branch** — PRO layout may land after Codex trace contract base `a667d551`.

---

## Documentation index

- [`JUDGES_START_HERE.md`](JUDGES_START_HERE.md) — judge walkthrough
- [`THE_STORY.md`](THE_STORY.md) — narrative
- [`AGENTIC_DEFENSE.md`](AGENTIC_DEFENSE.md) — threat model + Google mapping
- [`AMD_ROCM_STRATEGY.md`](AMD_ROCM_STRATEGY.md) — ROCm 10 / AMD Skills (no prod cutover before deadline)
- [`SELF_HEALING_SYSTEM.md`](SELF_HEALING_SYSTEM.md) — recovery / anti-freeze
