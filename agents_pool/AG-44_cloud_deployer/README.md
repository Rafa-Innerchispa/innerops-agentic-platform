# AG-44 Cloud Deployer

Status: **active cloud-control agent; legacy README was stale**.

AG-44 is the InnerOS cloud operations specialist for governed provider access, deployment planning, authorization and cloud evidence.

## Current runtime

Canonical runtime:

`platform/inneros_core_runtime/agents/ag44_cloud_deployer.py`

The runtime already provides substantially more than the original stub description.

### GCP
- provider/readiness status
- server-side `gcloud` authentication posture
- owner-consent flow without exposing credentials in chat
- project listing
- billing-account inspection
- allowlist concepts for projects/billing
- dry-run deployment planning
- human-gated apply boundary
- audit/evidence records

### Cloudflare
- DNS operations
- WAF hostname rules
- tunnel-ingress inspection
- health checks
- rollback-oriented operations
- server-side owner-vault secrets

### Other provider boundaries
- Azure dry-run/preflight when CLI is available
- Alibaba dry-run/preflight when CLI is available
- DigitalOcean AMD cloud control-plane scaffolding with guarded create/destroy boundaries

## Google / ACT III role

AG-44 is the cloud-control companion to the existing InnerOS Google stack:

- `gemini_runtime.py` — governed Gemini / Vertex provider
- `gcp_memory_bank.py` — Firestore agent-memory mirror
- `google_adk_a2a.py` — Google ADK / RemoteA2aAgent contract
- Gemini evidence to Firestore
- Pub/Sub event publishing
- Model Armor sanitization path

For ACT III, AG-44 should be used to prove one safe Google-backed path without weakening the local-first architecture:

`InnerOS local AMD execution -> sanitized event/evidence -> GCP/Firestore/PubSub -> optional Gemini specialist -> InnerOS governance`

## Safety model

AG-44 must never request or print raw passwords, service-account JSON, tokens or private keys in agent messages.

Cloud mutations remain gated by:
1. server-side provider authorization;
2. allowlist/scope validation;
3. explicit owner approval;
4. provider-specific apply enablement;
5. post-action verification/evidence.

## Truth boundary

- Readiness/preflight/dry-run tools are not proof of a successful cloud mutation.
- Google ADK contracts marked `NON-LIVE` must remain labeled that way until live evidence exists.
- Cloud provider integration should extend InnerOS, not bypass InnerOS approval/evidence boundaries.

## ACT III next verification

1. Run AG-44 GCP status/auth bootstrap.
2. Confirm the intended project server-side.
3. Capture one safe Firestore and/or Pub/Sub event from an InnerOS ACT III correlation.
4. If quota permits, capture one bounded Gemini/Vertex specialist response.
5. Preserve correlation ID, provider/runtime identity and evidence.
6. Do not block the core AMD/Bellini demo if the optional Google path is unavailable.
