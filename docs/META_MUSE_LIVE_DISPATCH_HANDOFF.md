# Meta Muse Wonder live dispatch — governed integration handoff

Status: **offline adapter implemented and tested, MCP production handler NOT wired**.

## Context
The currently registered `model.frontier.reason.v1` capability rejects real
prompts with `Synthetic prompt must start with the fictional-lab provenance marker`.
Changing the prompt to satisfy that marker is **not** a valid way to trigger a
real paid call. Antigravity separately verified a direct provider API response
on 2026-11-08 (receipt `resp_6af00f82765c9f87a253466a`). Neither that
receipt nor the offline tests prove that this MCP capability is production-ready.

## Module
`platform/inneros_core_runtime/meta_muse_live_dispatch.py` provides a single,
non-retrying, fixed-model HTTP POST to Meta Responses API, requiring:
- A grant from a **trusted** store with **atomic consume-once semantics**.
- Owner approval, matching Meta provider/project/model, timezone-aware TTL.
- Output and prompt size caps.
- A **verified external billing hard limit** on the Meta API account. A token
  limit or user-written dollar value cannot enforce an actual provider spend cap.
- A server-side credential resolver that retrieves the Meta Model API key from
  the existing private Vault. Do not use a Muse Code subscription token.
- No shell, tool execution, implicit retries, or production mutations.

The adapter deliberately does **not** expose a new public tool, read Vault
on its own, update production workers, or change the existing synthetic route.

## Remaining deployment work (privileged operator only)
1. Locate the registered handler of `model.frontier.reason.v1` in the active
   MCP Small service. Confirm its deployment source and baseline.
2. Keep the existing synthetic lab endpoint functioning; add an explicit
   real-dispatch branch only under approved scope/grant and **never** via a
   fictional provenance marker.
3. Provide the actual grant ledger/atomic redemption implementation and
   private Vault resolver to `invoke_muse`.
4. Enforce Meta project billing limits upstream, and durably reconcile the
   returned provider response ID/usage to MetaGrantLedger. If ledger write
   fails, do not retry paid inference automatically.
5. Gate to trusted `ralfia:agents` access; deny general `ralfia:read` callers.
   Add a client-facing receipt without secrets.
6. Run the existing offline tests, a single user-authorized live request with a
   small output limit, verify no unauthorized charges, then deploy with backup,
   health probe and rollback. Never restart the entire platform.
7. Only after successful live proof, expose a ChatGPT workflow invoking Muse
   to diagnose InnerOS coordination and dispatch coding work to local Dev Swarm.

## Verified tests
`python -m pytest platform/tests/test_meta_muse_live_dispatch.py -q`
=> 9 passed, 2 parameterized subtests passed (2026-11-08).

## Security limitations
The adapter assumes `TrustedGrantStore.redeem_once` is genuinely atomic,
trustworthy and durable across hosts/processes. The module does not establish
that fact. It also assumes account-level hard billing controls have been
verified independently. These are mandatory gates, not TODOs to silently skip.
