# Google / All Things Agentic Compliance Evidence — 2026-08-29

## Rule discovered during final hardening

The current All Things Agentic Hackathon requirements state that every project must use **Gemini 3.5 or newer**, plus at least one Google agent framework and at least one Google Cloud infrastructure service.

InnerOS uses a strict evidence rule: source code, a configured provider, a simulated fallback or a degraded response never counts as LIVE PASS.

## Repository integration

Canonical repository: `Rafa-Innerchispa/innerops-agentic-platform`

Google runtime integration merged to `main` through PR #19.

- Google integration source head: `3a8e0e0f64b496a13ce50a9967840f1f424ef523`
- Canonical merge SHA: `8cad655329184fe15269965476a11e19b25e7cdf`
- Source compile check: PASS for Gemini runtime, Google ADK/A2A, Memory Bank, tracking envelope, A2A OIDC and their three test modules.

## Compliance matrix

| Requirement / component | Source integration | Live evidence | Status on 2026-08-29 | Required final evidence |
| --- | --- | --- | --- | --- |
| Gemini 3.5+ | `gemini_runtime.py` declares `gemini-3.5-flash` | Previous live proof was Gemini 2.5 Flash, not sufficient | **LIVE FAIL / source present** | successful Gemini 3.5+ Vertex/API invocation in strict cloud-required mode |
| Google agent framework | `google_adk_a2a.py` + Google GenAI SDK runtime | ADK module explicitly marks itself NON-LIVE pending live proof | **LIVE PENDING** | live ADK/GenAI SDK execution under same correlation ID |
| Cloud Run | deploy/runtime path exists | direct check from current MCP blocked by `gcloud_missing` | **VERIFY IN GOOGLE-CAPABLE ENV** | revision, traffic and public/backend demo evidence |
| Firestore | Gemini runtime writes execution evidence | direct check from current MCP blocked by `gcloud_missing` | **VERIFY LIVE** | Firestore record for demo correlation ID |
| Pub/Sub | Gemini runtime publishes to `inneros-events` | direct check from current MCP blocked by `gcloud_missing` | **VERIFY LIVE** | published event for same correlation ID |
| Memory Bank | `gcp_memory_bank.py` integrated | needs live/synchronized state evidence | **VERIFY LIVE** | Memory Bank / state evidence tied to demo run |
| Model Armor | prompt and response sanitization integrated in `gemini_runtime.py` | needs live call evidence | **VERIFY LIVE** | sanitized benign request + blocked/flagged policy fixture without exposing secrets |
| Agent Identity / IAM | least-privilege deploy script integrated | current identity/roles need fresh cloud readback | **VERIFY LIVE** | dedicated runtime service account and exact minimal roles |
| Agent Gateway / bounded tools | `ToolSpec` risk/approval boundaries and InnerOS A2A/tool gateway | source path present | **SOURCE PASS, LIVE PENDING** | one real bounded tool call and verified result |
| Agent Registry | canonical InnerOS agent catalog projected to A2A Agent Cards | previously verified locally: 55 functional + 5 special cards | **LOCAL LIVE PASS** | preserve count and no tool loss after Google deploy |
| Agent Runtime | local InnerOS runtime + Google provider adapter | Google runtime live state pending | **PARTIAL** | Gemini 3.5 live execution in governed runtime |
| Agent Observability | tracking envelope / correlation IDs integrated | cloud trace/log evidence pending | **VERIFY LIVE** | same correlation ID in model, state, Pub/Sub and logs/trace |
| A2A | merged canonical A2A registry/runtime | prior local A2A evidence exists | **LOCAL LIVE PASS** | regression check after Google deploy |

## Strict final E2E gate

A final Google PASS requires one reproducible run that proves:

1. Real input/signal enters InnerOS.
2. InnerOS routes the relevant reasoning step to **Gemini 3.5 or newer**.
3. Model Armor evaluates the prompt/response path.
4. Gemini requests or participates in a **bounded real tool action**.
5. InnerOS authorizes and executes the action without arbitrary shell or unrestricted secrets.
6. State/evidence is persisted in Firestore and/or synchronized Memory Bank.
7. An event is published through Pub/Sub.
8. The entire run carries one correlation ID through model execution, state and observability/logging.
9. Result is independently verified by InnerOS / Integration Guardian.
10. Cloud Run revision and Google Cloud backend are visibly demonstrable in the submission video.

Any simulated/degraded fallback is FAIL for this gate.

## Active verification ownership

- Ops task: `ops_98466717a2b7` — P0 harden InnerOS for All Things Agentic with Gemini 3.5.
- Related runtime task: `ops_135effcb396e` — Gemini 3.5 + ADK native runtime.
- Antigravity handoff: `msg_613c8c99547c008f`.

The handoff explicitly requires strict cloud mode, real Gemini 3.5+, bounded tool evidence, Firestore, Pub/Sub, Model Armor, IAM, Cloud Run and logs/traces before declaring PASS.

## Submission implication

Do **not** update Devpost to claim Gemini 3.5 LIVE merely because this source is merged. Update the submission only after the strict E2E gate above produces reproducible evidence. This protects the project from an eligibility claim that the runtime cannot prove.
