import test from 'node:test';
import assert from 'node:assert/strict';
import { evaluateEvidence } from '../scripts/integration-guardian.mjs';

test('accepts isolated development branch with code, tests and passing suite', () => {
  const result = evaluateEvidence({
    branch: 'local-agent/feature-x',
    taskKind: 'development',
    changedFiles: ['src/server.js', 'tests/demo.test.mjs'],
    testCommand: 'npm test',
    testExitCode: 0,
    skippedTests: 0,
  });
  assert.equal(result.ok, true);
  assert.equal(result.gate, 'PASS');
});

test('rejects docs-only development output', () => {
  const result = evaluateEvidence({
    branch: 'local-agent/docs-only',
    taskKind: 'development',
    changedFiles: ['README.md', 'docs/status.md'],
    testCommand: 'npm test',
    testExitCode: 0,
    skippedTests: 0,
  });
  assert.equal(result.ok, false);
  assert.ok(result.failures.includes('docs_only_development_output'));
});

test('rejects skipped or failed tests', () => {
  const result = evaluateEvidence({
    branch: 'local-agent/broken',
    taskKind: 'development',
    changedFiles: ['src/server.js', 'tests/demo.test.mjs'],
    testCommand: 'npm test',
    testExitCode: 1,
    skippedTests: 1,
  });
  assert.equal(result.gate, 'REJECT');
  assert.ok(result.failures.includes('tests_failed:1'));
  assert.ok(result.failures.includes('tests_skipped:1'));
});

test('rejects direct feature work on main and generated artifacts', () => {
  const result = evaluateEvidence({
    branch: 'main',
    taskKind: 'development',
    changedFiles: ['src/server.js', 'tests/demo.test.mjs', 'node_modules/pkg/index.js'],
    testCommand: 'npm test',
    testExitCode: 0,
    skippedTests: 0,
  });
  assert.equal(result.gate, 'REJECT');
  assert.ok(result.failures.includes('protected_branch_direct_work'));
  assert.ok(result.failures.some((x) => x.startsWith('generated_artifacts:')));
});
