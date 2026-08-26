const PROVENANCE = new Set(['measured', 'inferred', 'manual', 'estimated']);
const ACTOR_TYPES = new Set(['human', 'agent', 'system']);

function requireText(value, field) {
  if (typeof value !== 'string' || value.trim() === '') {
    throw new TypeError(`${field} is required`);
  }
  return value.trim();
}

function asIso(value, field) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) {
    throw new TypeError(`${field} must be a valid date`);
  }
  return date.toISOString();
}

export function createProductivityEvent(input) {
  if (!input || typeof input !== 'object') throw new TypeError('event input is required');

  const provenance = requireText(input.provenance, 'provenance').toLowerCase();
  if (!PROVENANCE.has(provenance)) throw new TypeError(`unsupported provenance: ${provenance}`);

  const actorType = requireText(input.actorType, 'actorType').toLowerCase();
  if (!ACTOR_TYPES.has(actorType)) throw new TypeError(`unsupported actorType: ${actorType}`);

  const startedAt = asIso(input.startedAt, 'startedAt');
  const endedAt = asIso(input.endedAt ?? input.startedAt, 'endedAt');
  if (Date.parse(endedAt) < Date.parse(startedAt)) throw new RangeError('endedAt cannot be before startedAt');

  const event = {
    eventId: requireText(input.eventId, 'eventId'),
    tenantId: requireText(input.tenantId, 'tenantId'),
    projectId: input.projectId ? requireText(input.projectId, 'projectId') : null,
    taskId: input.taskId ? requireText(input.taskId, 'taskId') : null,
    actorType,
    actorId: requireText(input.actorId, 'actorId'),
    eventType: requireText(input.eventType, 'eventType'),
    source: requireText(input.source, 'source'),
    provenance,
    startedAt,
    endedAt,
    evidenceRef: input.evidenceRef ? String(input.evidenceRef) : null,
    metadata: input.metadata && typeof input.metadata === 'object' ? { ...input.metadata } : {},
  };

  return Object.freeze(event);
}

export function eventDurationMs(event) {
  return Math.max(0, Date.parse(event.endedAt) - Date.parse(event.startedAt));
}

export function eventDedupeKey(event) {
  const e = createProductivityEvent(event);
  return [e.tenantId, e.actorType, e.actorId, e.eventType, e.source, e.startedAt, e.endedAt, e.evidenceRef ?? ''].join('|');
}

export function dedupeProductivityEvents(events) {
  const seenIds = new Set();
  const seenEvidence = new Set();
  const result = [];

  for (const raw of events ?? []) {
    const event = createProductivityEvent(raw);
    const key = eventDedupeKey(event);
    if (seenIds.has(event.eventId) || seenEvidence.has(key)) continue;
    seenIds.add(event.eventId);
    seenEvidence.add(key);
    result.push(event);
  }
  return result;
}

export const PRODUCTIVITY_PROVENANCE = Object.freeze([...PROVENANCE]);
