# Local-First Execution Policy

Owner policy id: `owner-local-first-20260901`

Development delegation in InnerOS is local-first by default. Coding, heavy reasoning, code review, refactor, basic ops, builds and tests must route to local providers before paid external execution.

Canonical preferred route:

- Provider: `local-amd-5`
- Model: `QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ`
- Fallback/test node: `local-intel-4`

External Codex, Cursor, Antigravity or cloud inference is allowed only for orchestration, provider-specific IDE/session work, local capability failure, local unavailability, or explicit owner override. Paid execution must carry:

- `execution_policy=local_first`
- `owner_policy_id=owner-local-first-20260901`
- `preferred_provider`
- `preferred_model`
- `fallback_reason`
- `approval_id`

No task may be reported as running without durable task id, correlation id, idempotency key and a real worker/session/process evidence chain.
