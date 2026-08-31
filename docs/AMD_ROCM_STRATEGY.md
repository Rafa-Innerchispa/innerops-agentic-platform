# AMD ROCm & Skills strategy (InnerOS)

**Status:** Active strategy — **no risky production ROCm major cutover** immediately before hackathon submission.

---

## Goals

1. Keep **production inference** on AMD `.5` stable (vLLM `:8000`, Ollama, Lemonade multimodal).
2. Run **ROCm 10 canary** isolated from production until PASS checklist completes.
3. Wire **AMD Skills** (local-ai-use, rocm-doctor, Magpie/TraceLens) into Cursor/Codex/Antigravity without duplicating MCP coordination.
4. Document evidence for judges without claiming GPU paths that are not running.

---

## Fleet layout

| Node | Role | GPU / AI |
|------|------|----------|
| **192.168.1.4** (Intel) | Services, MCP bridge, HA fallback | CPU inference, tests |
| **192.168.1.5** (AMD) | Primary local coding + inference | Radeon AI PRO R9700, vLLM, Ollama, Lemonade `:13305` |

MCP for IDEs on Windows: `http://192.168.1.5:8102/mcp` (never `127.0.0.1` from Windows).

---

## ROCm 10 canary (isolated)

- **Baseline:** Existing ROCm on `.5` serves production `:8000`.
- **Canary:** ROCm 10 + AMD Skills experiments in **separate** env/worktree — no cutover to `:8000` until canary PASS.
- **Skills:** `rocm-doctor`, Magpie kernel eval, TraceLens analysis — diagnostics only unless ops explicitly approves apply.
- **Evidence:** Canary logs + `rocm examine` / `hipInfo` snapshots stored in ops evidence, not invented in UI.

---

## Lemonade (multimodal local)

Per workspace `AGENTS.md` / amd-skills local-ai-use:

- Images: `http://localhost:13305/api/v1/images/generations` (SD-Turbo)
- TTS: `/v1/audio/speech` (kokoro-v1)
- STT: `/v1/audio/transcriptions` (Whisper-Tiny)

Used in **femar ARIA** and agent harness — not a substitute for A2A agent communication.

---

## Judge Console truth (GPU-related)

| Surface | Honest state |
|---------|--------------|
| **Local AMD (Test 6)** | LIVE when Ollama/vLLM route succeeds; PARTIAL if busy |
| **FunctionGemma (Test 3)** | Historical verification; current endpoint may be NOT_RUNNING |
| **MI325X burst** | Preflight/dry_run only in UI; production GPU destroyed by owner approval — no judge-triggered deploy |

---

## What we are not doing (pre-submission)

- Force-upgrading production ROCm on `.5` during hackathon deadline week
- Recreating MI325X cloud GPU without owner approval
- Presenting Lemonade/ROCm as **inter-IDE communication** (that is MCP + A2A)

---

## Related

- Workspace skill: `.agents/skills/rocm10-a2a-skills/SKILL.md`
- [`ALL_THINGS_AGENTIC.md`](ALL_THINGS_AGENTIC.md) — hackathon evidence map
- [`JUDGES_START_HERE.md`](JUDGES_START_HERE.md) — judge GPU truth states
