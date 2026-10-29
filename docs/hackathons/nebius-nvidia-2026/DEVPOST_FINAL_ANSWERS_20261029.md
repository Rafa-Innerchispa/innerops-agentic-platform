# Devpost final submission worksheet — 29 Oct 2026

**Hackathon:** Nebius x NVIDIA Global AI Hackathon
**Project:** https://devpost.com/software/inneros-infrastructure-guardian
**Official deadline:** 2026-10-30T17:00:00Z = 12:00 Ecuador, 30 Oct 2026
**State when drafted:** project published, not submitted; no public video_url.
**Owner scope:** Only ChatGPT + owner interact with Devpost; Codex has no permission to edit it or create more videos.
**Source:** authenticated Devpost submission_requirements October 29 and public GitHub evidence.

## Submission-ready grounded text (field ID in parentheses)

- **(28262) Organization:** InnerChispa LLC. Only if entering as an organization; otherwise N/A.
- **(28265) Residence:** Ecuador. Confirm at submission; country of residence not company registration.
- **(28266) Canada province:** N/A, only if no teammate resides in Canada.
- **(28267) Track:** Physical AI.
- **(28268) Existing project:** Existing. InnerOS existed before 26 Aug 2026. New sponsor-specific work is below.
- **(28269) Significant changes since cutoff:** We extended the existing local-first InnerOS Device Fabric with a Nebius Token Factory adapter for an open NVIDIA Nemotron model, a privacy sanitizer, governed reboot / port PoE-cycle / recovery-verification capabilities, idempotent audit receipts, a five-route Guardian API contract, and a publicly accessible application walkthrough. We added a public Apache-2.0 repository and documented both successful live cloud inference and safe simulated actions. Existing local orchestration and voice/telephony are reused, but live phone approval is not yet bound to this Guardian demo.
- **(28270) Repository:** https://github.com/Rafa-Innerchispa/inneros-nebius-nvidia-physical-ai-2026
- **(28271) Demo:** https://hotels-survey-cite-webmasters.trycloudflare.com . URL from last verified deployment 27 Oct; MUST re-test on 29/30 Oct because ephemeral Quick Tunnel may change.
- **(28272) Model and rationale:** `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` via Nebius Token Factory. We selected a smaller NVIDIA open model for structured, bounded diagnosis and recommendations under approval policy, rather than allowing a larger model to exercise physical authority. One owner-approved real inference was recorded on 27 October: 308 input tokens, 692 output tokens, and a successful finish_reason=stop; this does not constitute latency or accuracy benchmarking.
- **(28273) Quality:** [OWNER'S 1-10 SCORE REQUIRED]. Factual note: A single real inference returned structured root cause, severity, impact, governed reboot recommendation, approval requirement and verification plan for synthetic AP telemetry. One successful response is insufficient to quantify production reliability or true physical diagnosis accuracy.
- **(28274) Tuning approach:** Prompt engineering and JSON-structured response, no fine-tuning. Input is sanitized and bounded. Policy requires explicit approval and provider receipts, with dry-run as the default; all physical mutations are outside cloud inference.
- **(28275) Comparison:** We did not run a controlled benchmark between Nemotron and other models on the same dataset. InnerOS has independent local model infrastructure, but the Guardian demo uses a deterministic heuristic fallback, not a measured local-Qwen model comparison. We therefore do not claim numerical superiority in quality, price or latency.
- **(28276) Most useful Nebius capabilities:** Token Factory's hosted OpenAI-compatible endpoint, authenticated model catalog and returned response identifiers and token usage enabled real NVIDIA inference while keeping hardware control in a separate private InnerOS Gateway. We did not deploy our own Nebius GPU instance or use Serverless Jobs. The public console shows a previously recorded real-model receipt; routine demo clicks are safe local heuristic actions with no billable inference.
- **(28277) Recommendation likelihood:** [OWNER'S 1-10 SCORE REQUIRED]. Factual note: Successful API response, bounded requests and useful provider receipts; only limited testing, not a production load test.
- **(28278) Experience rating:** [OWNER'S 1-10 SCORE REQUIRED]. Factual note: The first approved attempt failed parsing; the adapter was corrected to retain provider usage and cap output. The second approved attempt succeeded. No measured comparative benchmark.
- **(28279) Improvements:** Schema-constrained JSON outputs, clearer per-model token budgets, diagnostic information for incomplete responses, and accessible cost/credit visibility would improve predictable integration and evaluation.
- **(28280) Nemotron team requests:** More examples of safe structured decisions for infrastructure incident response, calibrated uncertainty and confidence, and transparent documented behavior for tool-use boundaries, JSON completion and truncation.
- **(28282) Tavily use:** No functional Tavily runtime call is included in the delivered repo or verified pipeline; answer No unless owner has separately added and verified one.
- **(29059) AI tools:** NVIDIA Nemotron 3 Nano through Nebius Token Factory for documented inference, ChatGPT and Codex for research/code/documentation, Cursor and local developer tools as used across the broader InnerOS development. Remove any item not actually used for this hackathon iteration.
- **(29060) Learning level:** [OWNER SELECTS None / Moderate / Significant].
- **(29061) Career value:** [OWNER SELECTS Yes / No].

## Fields requiring explicit owner review (DO NOT infer/legal certify)

- (28261) Submitter Type: Individual / Team / Organization (owner/team arrangement).
- (28262) Organization Name: InnerChispa LLC if applicable, else N/A.
- (28266) N/A only if no team members reside Canada.
- (28273), (28277), (28278): Owner's 1-10 ratings.
- (28283) Legal attestation: all team members are adults by local legal standard. Never check without owner's explicit confirmation.
- (28284) Legal attestation: all team members are not employees/representatives/agents of promotional entities. Never check without owner's confirmation.
- (29060), (29061): Subjective personal outcomes.
- (28281) Optional Builders & Brews city: only if actually attended a participating event.
- **Video:** Public YouTube/Vimeo URL required. Existing `media/inneros-guardian-demo-20261027.mp4` was accidentally generated by Codex and is NOT owner-approved. Review first. Phys AI needs >=60 seconds of hardware operating or key application modules when no hardware component. Edited one-fps frames may need replacement/continuous screen recording.

## Explicit truth boundaries

- REAL: Nebius Token Factory inference with NVIDIA Nemotron 3 Nano. Receipt: https://github.com/Rafa-Innerchispa/inneros-nebius-nvidia-physical-ai-2026/blob/main/examples/nebius-live-receipt.json
- REAL: isolated Guardian HTTP API test suite and browser dry-run operation as of 27 Oct.
- REAL separate feature: Owner confirmed by chat on 29 Oct that InnerOS via Home Assistant/VoiceOps placed a call and owner spoke to the agent. This does NOT yet verify Guardian incident -> authenticated telephone approval -> capability action.
- SIMULATED: physical recovery, AP / port reboot and recovery status in public demo.
- BLOCKED: public phone-approval button; no callback authority proof for Guardian.
- UNVERIFIED CURRENT: ephemeral Cloudflare Quick Tunnel availability on 29 Oct.
- NOT SUBMITTED: Devpost entry; video_url was null 29 Oct.

## Minimal remaining critical path

1. Verify demo URL immediately before submission; if dead use fresh deployed URL.
2. Owner reviews/approves a publicly playable <=3min YouTube/Vimeo demo satisfying track footage rule.
3. Owner confirms subjective scores/experience and both legal checkboxes.
4. ChatGPT fills custom_answers using these exact Devpost field IDs and submits through the Devpost connector.
5. Check returned status=Submitted, submission_id, URL and timestamp.

Do not spend another night adding optional Alexa/Ring/phone functionality. It is not a gating submission requirement.
