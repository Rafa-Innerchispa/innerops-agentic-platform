# InnerOS Muse Wonder Self-Healing | Measurement protocol
2026-11-02 · Owner: InnerChispa LLC · Status: instrumented OFFLINE; Meta Wonder real inference NOT_RUN.

## Hypothesis, suitable for Meta Startup Track
Can the same governed InnerOS that diagnoses physical infrastructure also detect and repair defects in its own agent coordination? Compare primary AMD Qwen local vs a one-request approved Muse Wonder 1.0 specialist on the SAME measured coordination incident. Correctness requires an independent test rerun, not an agent claiming completion. A failed attempt still counts as a reproducible experiment.

## Real baseline, not a toy failure
GitHub Actions: https://github.com/Rafa-Innerchispa/innerops-agentic-platform/actions/runs/41510104055
333 passed, 4 failed, 13 subtests passed.
Affected test cases:
- test_local_model_router_fallback::test_failed_fallback_remains_fail_closed
- test_ops_auto_claim_admission::test_manual_tasks_are_never_auto_claimed
- test_ops_antigravity_false_completion_regression::test_antigravity_headless_script_declares_bounded_executor_plan
- test_provider_execution_trust_boundary::test_codex_real_path_blocked_without_grant_and_env

These are genuine failed assertions, not proof each implementation is defective. Verify whether changed secure failure responses invalidate stale test expectations before editing security controls.

## Architecture and safety
1. CORE owns keys: owner_vault:model_api_provider/meta_model_api_key. Hackathon is just a client.
2. Source: before CI SHA/run, sanitized failing assertions, controlled synthetic test case. No real user/customer data, IP addresses, secrets, raw ops queue or proprietary source without written data-release approval.
3. Local Qwen tries first; record model version, hashes, inference latency/tokens if local service exposes them, and proposed patch.
4. Wonder is escalation only (model muse-wonder-1.0, Standard). Its API call is NOT the same as a successful self-heal; store provider ID/status and outputs privately, summarize safely.
5. Owner authorizes model, prompt SHA, reasoning effort, output cap, predicted spend, TTL and project_id, individually. No indefinite or anonymous grants; do not call until legacy HMAC bypass and unsourced receipt reconciliation are fixed.
6. A local executor applies a reviewed patch in an isolated worktree only. Diff recorded; no production restarts, customer infrastructure or payment settings.
7. Re-run identical baseline tests and related suite after changes, collect independent CI evidence; no auto-retry loops. Roll back if regression.
8. Preserve audit event hash and copy the final hash into a separately controlled evidence record so database edits are discoverable.

## Measurements to capture
Mandatory per run: experiment ID, case ID, project ID, baseline SHA/URL, tested SHA, model/model version, local/external policy, provider ID, response ID, request ID, reasoning effort, output cap, timestamps, wall latency, time to first token if streaming, prompt/context byte and token counts, cached input, output tokens, hidden reasoning, total tokens, official list-price estimate, actual verified billed credits when available, number and type of tools, task iterations, rejections, timeouts, retries, failures and success truth flags.
Engineering: changed files/lines, diff hash, approvals and review time, baseline tests/pass/fail/skip, post-tests/pass/fail/skip, before/after CI run URLs, targeted test duration, patch application time, number of rollbacks, new regressions, reason for unresolved.
Agent health: tasks claimed, duplicate claims, missing ACK, false completion claims, dangling/looping tasks, time to identify root cause, time until verified fix, and human time.
Reproducibility: source version, dependency versions, temperature/seed if controllable, hardware/backend, exact safe scenario digest, and provenance.
Reliability: mark NOT_RUN, INCOMPLETE, BLOCKED, CANDIDATE_PATCH, TESTS_PASSED_UNVERIFIED or VERIFIED_HEAL. One specimen does not support p50/p95 population or statistical superiority claims.

## Instrumentation included in this repository
File: platform/inneros_core_runtime/muse_experiment_metrics.py, pure stdlib.
- price_quote / quote_from_response: Standard mode list price, accounting for cached input and hidden reasoning included in output. Never invent a provider-billed charge.
- ExperimentJournal(path): private SQLite with atomic SHA-256 event chaining, case IDs and allowlisted telemetry fields. Only store event metadata; raw prompt, API key, customer memory and private CI logs are rejected.
- score_case(events): baseline-vs-after failures and evidence gaps. Always marks claim_self_healed FALSE until external evidence is independently checked.
Tests: platform/tests/test_muse_experiment_metrics.py. CI: .github/workflows/muse-self-heal-metrics.yml.
The existing InnerOS funding_registry and MetaGrantLedger are authoritative for actual provider spending. This journal is experimental telemetry, not a substitute for trusted billing or signed grants.

## Standard Model API pricing (confirmed 2026-11-02)
Muse Wonder 1.0: $4/1M uncached input, $0.20/1M cached input, $20/1M output including hidden reasoning.
Muse Spark 1.3: $1.25/1M uncached input, $0.15/1M cached input, $4.25/1M output.
Example 10k input + 3k output: Wonder $0.10, Spark $0.02525 (before tool charges).
Official: https://dev.meta.ai/docs/pricing-rate-limits and https://dev.meta.ai/docs/models

## Credit deadline
The email from Cerebral Valley 2026-10-26 says to CLAIM $150 by Wed November 4 at 9 PM Eastern. Credits distributed "in batches" = distribution scheduling, not recurring installments. Owner's screenshot shows $150 applied.
This is NOT an expiry date. Official terms section 13.3 says unused credits MAY expire on an account-specific date and are not reinstated: https://dev.meta.ai/legal/terms-of-service .
Exact current available amount, promo expiry and Wonder eligibility are NOT independently verified. Read authenticated Billing details / Usage after owner identity confirmation or contact Meta support. Do not claim $150 unspent or indefinite validity.
Standard mode generally does not use content to train Meta, but the owner's FREE CREDIT billing banner had a separate content-use disclosure; until clarified keep external inputs strictly synthetic.

## Immediate pilot protocol
- Verify Wonder appears under the same team and the promotional award applies. Check Model API Billing and no hidden charge/credit restriction.
- Reconcile Meta Spark's previous 300-token incomplete receipt into the SAME central ledger used by the live MCP. As last checked, live usage returned 0 despite Antigravity claiming a receipt on inneros-5-lan.
- Fix legacy HMAC grant acceptance without expiry and prohibit unauthenticated reconciliation of arbitrary receipt dictionaries.
- Create a synthetic agent-coordination reproduction derived from the four genuine failure names, not a dump of private source.
- Local Qwen baseline, then one explicitly owner-authorized Wonder call at bounded model-specific spend, single attempt, no paid agent loop.
- Store sanitized response, genuine receipt and list-price quote; human reviews suggestion, local worktree executes, independent CI verifies and rollback if necessary.
- Final judge evidence: BEFORE (4 failures), MODEL (real reasoning / refusal / incomplete as observed), PATCH (actual reviewed diff), AFTER (actual tests), COST (billing/estimate distinguished) and a provenance badge on each.

## Proposed cost cap (not yet configured, not an authorization)
First Wonder request budget <= $0.50 and max 8,192 output tokens, 1 call, no tools. Preflight uses a conservative token count; do not dispatch if the credit grant's expiration or the hard local budget is uncertain. The owner can grant another separate request after reviewing the first receipt. No model can self-approve the next call.

## Public release boundary
Do not make the API key accessible as standalone proxy/model aggregator. Use only InnerOS integrated product and authorized team under the Meta terms. No public anonymous paid inference. Demo can show read-only recorded evidence with truthful labels.
