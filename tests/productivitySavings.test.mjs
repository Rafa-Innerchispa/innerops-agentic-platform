import assert from 'node:assert/strict';
import test from 'node:test';
import { createSavingsEstimate, aggregateSavings } from '../src/productivitySavings.js';

test('computes conservative time savings without treating agent runtime as human time', () => {
  const estimate = createSavingsEstimate({
    taskKey: 'ha-unifi-broadlink-cleanup-20260826',
    humanBaselineMinutes: 120,
    assistedMinutes: 10,
    confidence: 'medium',
    provenance: 'estimated+measured',
    evidenceRefs: ['ops_e418823d2d5a', 'ops_81d00b3a2d7e'],
  });
  assert.equal(estimate.savedMinutes, 110);
  assert.equal(estimate.reductionRatio, 110 / 120);
  assert.equal(estimate.speedMultiplier, 12);
});

test('never reports negative savings', () => {
  const estimate = createSavingsEstimate({ taskKey: 'slow-task', humanBaselineMinutes: 5, assistedMinutes: 9 });
  assert.equal(estimate.savedMinutes, 0);
  assert.equal(estimate.reductionRatio, 0);
});

test('aggregates multiple savings events using total baseline and assisted time', () => {
  const total = aggregateSavings([
    { taskKey: 'a', humanBaselineMinutes: 120, assistedMinutes: 10 },
    { taskKey: 'b', humanBaselineMinutes: 60, assistedMinutes: 15 },
  ]);
  assert.equal(total.humanBaselineMinutes, 180);
  assert.equal(total.assistedMinutes, 25);
  assert.equal(total.savedMinutes, 155);
  assert.equal(total.speedMultiplier, 7.2);
});
