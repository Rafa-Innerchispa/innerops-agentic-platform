# InnerOS | Dual-node HA gate and third-node expansion
Status: CODED / local tests only. NOT DEPLOYED and NOT VERIFIED.
Date: 2026-10-11
Correlation: inneros-ha-golden-flow-20261011

## Outcome required by the owner

InnerOS is one system with replaceable compute nodes, not an AMD service with
an optional Intel machine. Both nodes must continue work supported by their
resources when the other disappears. A later third server joins the same
registry, controls, task ledger and release process.

## Current read-only observations (not outage-drill evidence)

- AMD responds to observability checks: MCP and local inference processes,
  Temporal and NATS listener ports are present. The observed Temporal process
  uses `server start-dev`, which is NOT proof of a production-grade durable
  Temporal cluster.
- Intel responds to route and Python runtime checks, so its observability
  helper failure (return code 126) must not be reported as an offline host.
  Its project-specific .venv was not present at the resolved workspace path;
  the effective service-runtime environment remains unverified.
- A2A reports Temporal ready and production_enabled=true, but NATS and OTEL
  runtime flags are false. Listening ports do not establish durable event
  replication or cross-node traces.
- Scheduler is enabled (four concurrency slots) with zero active workers in
  the sampled instant. Enabled is not equivalent to processing tasks.
- The legacy `platform/scripts/deploy_platform_mirror_ha.sh` uses
  `rsync --delete` and performs multi-node service restarts. DO NOT RUN that
  script as a HA deployment gate until the release-controller preflight,
  exclusions, snapshots, immutable hashes and rollback have been proven.
  Running it is not part of this change.

## Capability-aware failover contract

1. **MCP read-only methods** may retry across healthy backends. On a backend
   outage, the request must preserve the original JSON-RPC semantics and the
   identity/authorization boundary.
2. **MCP mutating methods** must fail closed when the first backend's outcome
   is unknown, even if an idempotency key is present. The flag
   `INNEROS_MCP_SHARED_IDEMPOTENCY_PROVEN` defaults to disabled and must
   remain disabled until a common durable deduplication ledger is demonstrated
   with the same key on both hosts and a failed-response replay test.
3. **Inference** must be routed by model availability and measured capacity.
   Intel/Ollama can take the AMD/vLLM outage's *compatible* requests; it cannot
   promise to run AMD-size models. AMD can take Intel-compatible inference
   when the data, route and model remain accessible. No automatic paid-cloud
   escalation.
4. **Temporal/Mongo/NATS stateful workloads** cannot be declared HA merely
   because workers or ports exist on both machines. Verify shared persistent
   workflow history, database durability, event replay, a fencing lease and
   ownership reconciliation before promoting stateful active/standby.
5. **Physical node-specific services** (PBX, cameras, radio, connected
   interfaces) remain degraded/unavailable on the peer unless their hardware
   and configuration are genuinely reachable. Failover must report partial
   service, never fabricate equivalence.
6. **Third server** must be a registered additional backend with bounded
   capacity, trust scopes, last-known-good compatibility and telemetry.
   Never add it as an independent source of task truth.

## Certification gates

- Capture the effective runtime SHA and non-secret configuration profile on
  both nodes, backup manifest, service state, credentials availability via a
  secure vault, and live health before *any* promotion.
- Fix Intel's observability-helper exit 126 (diagnose permissions/executable,
  not host power), confirm its actual service venv, and inspect both sides.
- Promote one canary component on one host, verify hash, running service,
  request trace, persisted task result, and bounded rollback before touching
  the other host. Do not synchronize by deleting peer paths.
- Prove **AMD unavailable => Intel handles MCP and locally supported model
  requests** through isolated gateway proxies (not a destructive power test).
- Prove **Intel unavailable => AMD handles MCP/inference and permitted
  orchestration**, with durable task ownership. Separate stateful DB failover
  until independently certified.
- Prove the same request cannot finish twice during failover, including
  unknown outcome/retry and interrupted coordinator.
- Prove automatic recovery and return-to-normal without split brain;
  record task ID, trace, runtime SHA, worker, data evidence and timestamp.
- Establish and test immutable Last Known Good for *each host*, independent
  rollback and safe release tags. Do not tag a public release on CI alone.
- Configure required GitHub checks under admin-controlled branch protection.
  CI passing and merge are NOT production deployment.
- Only after these gates, evaluate K3s/Argo CD as phase two in an isolated
  noncritical component.

## What this change verifies

Offline federation tests cover Intel-to-AMD, AMD-to-Intel, adding a third
backend, total outage, mutating-call fail-closed behavior and the proof flag.
These tests do not establish production high availability.

## References

- PR #139: typed AG-41 evidence checks and CI-only runtime provenance.
- `platform/inneros_core_runtime/mcp_gateway/federation.py`
- `platform/tests/test_mcp_federation_failover_p0.py`
- `platform/scripts/deploy_platform_mirror_ha.sh` (legacy; unsafe without gate).
- `platform/docs/ADR_012_017_INNEROS_RELEASE_GOVERNANCE.md`
