export function classifyFailure(run) {
  if (!run || typeof run !== 'object') return { code: 'invalid_result', retryable: false };
  if (run.exitCode === 0) return { code: 'pass', retryable: false };
  const text = `${run.stdout || ''}\n${run.stderr || ''}`.toLowerCase();
  if (text.includes('command_not_allowlisted')) return { code: 'policy_command_rejected', retryable: false };
  if (text.includes('enoent') || text.includes('not found')) return { code: 'missing_dependency_or_file', retryable: false };
  if (text.includes('timeout') || text.includes('timed out') || text.includes('econnreset')) return { code: 'transient_runtime', retryable: true };
  if (text.includes('assert') || text.includes('test failed') || text.includes('not ok')) return { code: 'test_failure', retryable: true };
  return { code: 'unknown_failure', retryable: true };
}

export async function runWithBoundedRetry(executor, { maxAttempts = 2 } = {}) {
  if (typeof executor !== 'function') throw new TypeError('executor must be a function');
  const limit = Math.max(1, Math.min(3, Number(maxAttempts) || 1));
  const attempts = [];
  let previousSignature = null;

  for (let attempt = 1; attempt <= limit; attempt += 1) {
    const run = await executor(attempt);
    const diagnosis = classifyFailure(run);
    const signature = `${diagnosis.code}:${run.exitCode}:${String(run.stderr || '').slice(0, 160)}`;
    attempts.push({ attempt, run, diagnosis });

    if (run.exitCode === 0) return { ok: true, attempts, final: diagnosis };
    if (!diagnosis.retryable) return { ok: false, attempts, final: diagnosis, stopReason: 'non_retryable' };
    if (previousSignature === signature) return { ok: false, attempts, final: diagnosis, stopReason: 'no_measurable_progress' };
    previousSignature = signature;
  }
  return { ok: false, attempts, final: attempts.at(-1).diagnosis, stopReason: 'retry_budget_exhausted' };
}

export function buildRegressionReport(results = []) {
  const normalized = results.map((item) => ({
    module: item.module,
    ok: Boolean(item.ok),
    attempts: Array.isArray(item.attempts) ? item.attempts.length : 0,
    failure: item.ok ? null : item.final?.code || 'unknown_failure',
    stopReason: item.stopReason || null,
  }));
  return {
    ok: normalized.every((item) => item.ok),
    modules: normalized,
    failedModules: normalized.filter((item) => !item.ok).map((item) => item.module),
  };
}
