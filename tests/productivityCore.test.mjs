import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createProductivityEvent,
  dedupeProductivityEvents,
} from '../src/productivityEvents.js';
import {
  productivityKpiPrimitives,
  sessionizeHumanEvents,
  unionActiveMs,
} from '../src/productivitySessions.js';

const base = {
  tenantId: 'tenant-pcdoctor',
  projectId: 'inneros',
  actorType: 'human',
  actorId: 'founder',
  eventType: 'active_work',
  source: 'quick-log',
  provenance: 'manual',
};

function event(eventId, startedAt, endedAt, overrides = {}) {
  return createProductivityEvent({ eventId, startedAt, endedAt, ...base, ...overrides });
}

test('requires explicit provenance and tenant identity', () => {
  assert.throws(() => createProductivityEvent({ ...base, eventId: 'x', startedAt: '2026-08-25T10:00:00Z', provenance: 'magic' }), /unsupported provenance/);
  assert.throws(() => createProductivityEvent({ ...base, eventId: 'x', startedAt: '2026-08-25T10:00:00Z', tenantId: '' }), /tenantId is required/);
});

test('deduplicates both repeated ids and repeated evidence intervals', () => {
  const a = event('a', '2026-08-25T10:00:00Z', '2026-08-25T10:30:00Z', { evidenceRef: 'commit:1' });
  const sameId = { ...a };
  const sameEvidence = { ...a, eventId: 'b' };
  assert.equal(dedupeProductivityEvents([a, sameId, sameEvidence]).length, 1);
});

test('sessionizes nearby human work and splits after idle threshold', () => {
  const events = [
    event('a', '2026-08-25T10:00:00Z', '2026-08-25T10:20:00Z'),
    event('b', '2026-08-25T10:25:00Z', '2026-08-25T10:40:00Z', { provenance: 'measured', source: 'git' }),
    event('c', '2026-08-25T11:10:00Z', '2026-08-25T11:20:00Z'),
  ];
  const sessions = sessionizeHumanEvents(events, { idleThresholdMs: 10 * 60 * 1000 });
  assert.equal(sessions.length, 2);
  assert.equal(sessions[0].activeMs, 40 * 60 * 1000);
  assert.deepEqual(sessions[0].provenance, ['manual', 'measured']);
});

test('anti-double-counting unions overlapping intervals for the same actor', () => {
  const events = [
    event('a', '2026-08-25T10:00:00Z', '2026-08-25T11:00:00Z', { provenance: 'measured', source: 'screen-time' }),
    event('b', '2026-08-25T10:30:00Z', '2026-08-25T11:30:00Z', { provenance: 'inferred', source: 'git' }),
  ];
  assert.equal(unionActiveMs(events, { actorType: 'human' }), 90 * 60 * 1000);
});

test('human and agent time remain separate and are never treated as 1:1 savings', () => {
  const events = [
    event('h', '2026-08-25T10:00:00Z', '2026-08-25T11:00:00Z', { provenance: 'measured', source: 'screen-time' }),
    event('a', '2026-08-25T10:00:00Z', '2026-08-25T12:00:00Z', {
      actorType: 'agent', actorId: 'AG-25', provenance: 'measured', source: 'agent-log',
    }),
  ];
  const kpi = productivityKpiPrimitives(events);
  assert.equal(kpi.humanActiveMs, 60 * 60 * 1000);
  assert.equal(kpi.agentActiveMs, 120 * 60 * 1000);
  assert.equal(kpi.humanAgentRatio, 0.5);
  assert.equal(Object.hasOwn(kpi, 'hoursSaved'), false);
});
