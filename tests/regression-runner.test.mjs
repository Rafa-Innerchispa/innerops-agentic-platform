import test from 'node:test';
import assert from 'node:assert/strict';
import { classifyFailure, runWithBoundedRetry, buildRegressionReport } from '../scripts/regression-runner.mjs';

test('classifies incompatible policy command as non-retryable', () => {
  assert.deepEqual(classifyFailure({ exitCode: 1, stderr: 'command_not_allowlisted' }), {
    code: 'policy_command_rejected', retryable: false
  });
});

test('stops immediately for non-retryable failure', async () => {
  let calls = 0;
  const result = await runWithBoundedRetry(async () => {
    calls += 1;
    return { exitCode: 1, stderr: 'command_not_allowlisted' };
  }, { maxAttempts: 3 });
  assert.equal(calls, 1);
  assert.equal(result.stopReason, 'non_retryable');
});

test('stops when the same failure repeats without measurable progress', async () => {
  let calls = 0;
  const result = await runWithBoundedRetry(async () => {
    calls += 1;
    return { exitCode: 1, stderr: 'not ok assertion mismatch' };
  }, { maxAttempts: 3 });
  assert.equal(calls, 2);
  assert.equal(result.stopReason, 'no_measurable_progress');
});

test('allows a bounded retry when the failure changes and then passes', async () => {
  const runs = [
    { exitCode: 1, stderr: 'timeout while starting test' },
    { exitCode: 1, stderr: 'not ok assertion mismatch' },
    { exitCode: 0, stdout: 'ok' },
  ];
  const result = await runWithBoundedRetry(async (attempt) => runs[attempt - 1], { maxAttempts: 3 });
  assert.equal(result.ok, true);
  assert.equal(result.attempts.length, 3);
});

test('builds a module-level report without merging failed lanes', () => {
  const report = buildRegressionReport([
    { module: 'aria', ok: true, attempts: [{ attempt: 1 }] },
    { module: 'devices', ok: false, attempts: [{ attempt: 1 }], final: { code: 'test_failure' }, stopReason: 'retry_budget_exhausted' },
  ]);
  assert.equal(report.ok, false);
  assert.deepEqual(report.failedModules, ['devices']);
  assert.equal(report.modules[1].failure, 'test_failure');
});
