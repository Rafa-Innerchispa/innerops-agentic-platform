function requireMinutes(value, field) {
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) throw new TypeError(`${field} must be a non-negative number`);
  return number;
}

export function createSavingsEstimate(input) {
  if (!input || typeof input !== 'object') throw new TypeError('savings input is required');
  const humanBaselineMinutes = requireMinutes(input.humanBaselineMinutes, 'humanBaselineMinutes');
  const assistedMinutes = requireMinutes(input.assistedMinutes, 'assistedMinutes');
  const savedMinutes = Math.max(0, humanBaselineMinutes - assistedMinutes);
  const reductionRatio = humanBaselineMinutes > 0 ? savedMinutes / humanBaselineMinutes : 0;
  const speedMultiplier = assistedMinutes > 0 ? humanBaselineMinutes / assistedMinutes : null;
  return Object.freeze({
    taskKey: String(input.taskKey || '').trim(),
    humanBaselineMinutes,
    assistedMinutes,
    savedMinutes,
    reductionRatio,
    speedMultiplier,
    confidence: String(input.confidence || 'medium'),
    provenance: String(input.provenance || 'estimated'),
    evidenceRefs: Object.freeze([...(input.evidenceRefs || [])].map(String)),
    notes: String(input.notes || ''),
  });
}

export function aggregateSavings(estimates) {
  const normalized = (estimates || []).map(createSavingsEstimate);
  const humanBaselineMinutes = normalized.reduce((sum, item) => sum + item.humanBaselineMinutes, 0);
  const assistedMinutes = normalized.reduce((sum, item) => sum + item.assistedMinutes, 0);
  const savedMinutes = normalized.reduce((sum, item) => sum + item.savedMinutes, 0);
  return Object.freeze({
    eventCount: normalized.length,
    humanBaselineMinutes,
    assistedMinutes,
    savedMinutes,
    reductionRatio: humanBaselineMinutes > 0 ? savedMinutes / humanBaselineMinutes : 0,
    speedMultiplier: assistedMinutes > 0 ? humanBaselineMinutes / assistedMinutes : null,
  });
}
