import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { AgentRuntime, LocalAgentAdapter, GeminiAdkAdapter, RuntimeError } = require('../src/aria/runtime.js');

test('uses local provider first and avoids external calls by default', async () => {
  let externalCalls = 0;
  const local = new LocalAgentAdapter(async ({ input, context }) => ({ answer: `local:${input}`, tenant: context.tenantId }));
  const gemini = new GeminiAdkAdapter({ runAgent: async () => { externalCalls += 1; return { answer: 'cloud' }; } });
  const runtime = new AgentRuntime({ local, external: [gemini] });
  const result = await runtime.run({ agent: 'aria', input: 'status', context: { tenantId: 'tenant-a' } });
  assert.equal(result.provider, 'local');
  assert.equal(result.external, false);
  assert.equal(result.output.tenant, 'tenant-a');
  assert.equal(externalCalls, 0);
});

test('falls back to Gemini ADK only when external execution is explicitly allowed', async () => {
  const local = new LocalAgentAdapter(async () => { const err = new RuntimeError('local_busy', 'busy'); throw err; });
  const gemini = new GeminiAdkAdapter({ runAgent: async ({ agent, input, context }) => ({ agent, input, tenant: context.tenantId }) });
  const runtime = new AgentRuntime({ local, external: [gemini] });
  const result = await runtime.run({ agent: 'aria', input: 'summarize', context: { tenantId: 'tenant-b' }, allowExternal: true });
  assert.equal(result.provider, 'gemini-adk');
  assert.equal(result.external, true);
  assert.equal(result.output.tenant, 'tenant-b');
  assert.deepEqual(result.trace.map((x) => x.status), ['failed', 'ok']);
});

test('does not leak to external provider when external execution is disabled', async () => {
  let externalCalls = 0;
  const local = new LocalAgentAdapter(async () => { throw new RuntimeError('local_failed', 'failed'); });
  const gemini = new GeminiAdkAdapter({ runAgent: async () => { externalCalls += 1; return {}; } });
  const runtime = new AgentRuntime({ local, external: [gemini] });
  await assert.rejects(
    runtime.run({ agent: 'aria', input: 'x', context: { tenantId: 'tenant-c' } }),
    (error) => error.code === 'all_providers_failed' && error.details.trace.some((x) => x.reason === 'external_not_allowed')
  );
  assert.equal(externalCalls, 0);
});

test('requires tenant-scoped context before invoking any provider', async () => {
  let calls = 0;
  const local = new LocalAgentAdapter(async () => { calls += 1; return {}; });
  const runtime = new AgentRuntime({ local });
  await assert.rejects(
    runtime.run({ agent: 'aria', input: 'x', context: {} }),
    (error) => error.code === 'tenant_context_required'
  );
  assert.equal(calls, 0);
});

test('bounds retries per provider', async () => {
  let localCalls = 0;
  const local = new LocalAgentAdapter(async () => { localCalls += 1; throw new RuntimeError('transient', 'try again'); });
  const runtime = new AgentRuntime({ local, policy: { maxAttemptsPerProvider: 2 } });
  await assert.rejects(runtime.run({ agent: 'aria', input: 'x', context: { tenantId: 'tenant-d' } }), (error) => error.code === 'all_providers_failed');
  assert.equal(localCalls, 2);
});
