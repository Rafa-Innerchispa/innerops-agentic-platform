import test from 'node:test';
import assert from 'node:assert/strict';
import { computeProductivityRoi, adaptOpsTask, adaptGitCommit, mergeBackfill } from '../src/productivityRoi.js';

const base = {
  tenantId: 't1', projectId: 'p1', taskId: 'task1', actorId: 'rafael', source: 'manual', provenance: 'measured',
};

function event(eventId, actorType, eventType, start, end, metadata = {}) {
  return { ...base, eventId, actorType, eventType, startedAt: start, endedAt: end, metadata };
}

test('ROI uses explicit human savings and never converts agent hours 1:1', () => {
  const events = [
    event('h1', 'human', 'task_completed', '2026-08-25T10:00:00Z', '2026-08-25T11:00:00Z', { outcome: 'success', savedHumanHours: 2 }),
    event('a1', 'agent', 'automation', '2026-08-25T10:00:00Z', '2026-08-25T14:00:00Z', { delegatedHours: 1.5, externalCostUsd: 5 }),
  ];
  const result = computeProductivityRoi(events, { now: '2026-08-26T00:00:00Z', days: 7 });
  assert.equal(result.humanActiveHours, 1);
  assert.equal(result.agentActiveHours, 4);
  assert.equal(result.hoursSaved, 2);
  assert.equal(result.delegatedHours, 1.5);
  assert.equal(result.externalCostActual, 5);
  assert.equal(result.externalCostAvoided.medium, 50);
  assert.equal(result.valueRecovered.medium, 45);
  assert.equal(result.roi.medium, 9);
});

test('overlapping human events are not double counted and windows are enforced', () => {
  const events = [
    event('h1', 'human', 'commit', '2026-08-25T10:00:00Z', '2026-08-25T12:00:00Z'),
    event('h2', 'human', 'test_pass', '2026-08-25T11:00:00Z', '2026-08-25T13:00:00Z'),
    event('old', 'human', 'commit', '2026-07-01T10:00:00Z', '2026-07-01T11:00:00Z'),
  ];
  const result = computeProductivityRoi(events, { now: '2026-08-26T00:00:00Z', days: 7 });
  assert.equal(result.humanActiveHours, 3);
  assert.equal(result.eventCount, 2);
  assert.equal(result.commits, 1);
  assert.equal(result.testsPass, 1);
});

test('traditional vs assisted may provide savings without using agent duration', () => {
  const events = [event('x', 'human', 'task_completed', '2026-08-25T10:00:00Z', '2026-08-25T10:30:00Z', { traditionalHours: 6, assistedHours: 2 })];
  const result = computeProductivityRoi(events, { now: '2026-08-26T00:00:00Z', days: 30 });
  assert.equal(result.hoursSaved, 4);
  assert.equal(result.externalCostAvoided.conservative, 60);
  assert.equal(result.externalCostAvoided.strategic, 160);
});

test('ops and git adapters produce measured evidence and merge idempotently', () => {
  const ops = adaptOpsTask({ task_id: 'ops_1', status: 'completed', created_at: '2026-08-25T10:00:00Z', updated_at: '2026-08-25T11:00:00Z', assignee: 'AG-25', priority: 'p0' }, { tenantId: 't1' });
  const git = adaptGitCommit({ sha: 'abc', timestamp: '2026-08-25T12:00:00Z', author: 'rafael', message: 'feat' }, { tenantId: 't1', projectId: 'p1' });
  const merged = mergeBackfill({ existing: [ops], incoming: [ops, git] });
  assert.equal(merged.length, 2);
  assert.equal(ops.provenance, 'measured');
  assert.equal(git.evidenceRef, 'abc');
});

test('supports deterministic project lead time and success/rework rates', () => {
  const events = [
    event('1', 'human', 'commit', '2026-08-25T10:00:00Z', '2026-08-25T10:00:00Z', { outcome: 'success' }),
    event('2', 'agent', 'task_completed', '2026-08-25T12:00:00Z', '2026-08-25T13:00:00Z', { rework: true }),
  ];
  const result = computeProductivityRoi(events, { now: '2026-08-26T00:00:00Z', days: 30 });
  assert.equal(result.projectThroughput.p1.tasksCompleted, 1);
  assert.equal(result.projectThroughput.p1.leadTimeHours, 3);
  assert.equal(result.successRate, 0.5);
  assert.equal(result.reworkRate, 0.5);
});
