import { createProductivityEvent, dedupeProductivityEvents, eventDurationMs } from './productivityEvents.js';

function sessionKey(event) {
  return [event.tenantId, event.actorId, event.projectId ?? ''].join('|');
}

function mergeIntervals(intervals) {
  const ordered = [...intervals].sort((a, b) => a.start - b.start || a.end - b.end);
  const merged = [];
  for (const interval of ordered) {
    const last = merged[merged.length - 1];
    if (!last || interval.start > last.end) {
      merged.push({ ...interval });
    } else {
      last.end = Math.max(last.end, interval.end);
    }
  }
  return merged;
}

export function sessionizeHumanEvents(events, { idleThresholdMs = 15 * 60 * 1000 } = {}) {
  if (!Number.isFinite(idleThresholdMs) || idleThresholdMs < 0) {
    throw new TypeError('idleThresholdMs must be a non-negative number');
  }

  const humanEvents = dedupeProductivityEvents(events)
    .filter((event) => event.actorType === 'human')
    .sort((a, b) => Date.parse(a.startedAt) - Date.parse(b.startedAt));

  const sessions = [];
  for (const event of humanEvents) {
    const key = sessionKey(event);
    const start = Date.parse(event.startedAt);
    const end = Date.parse(event.endedAt);
    const previous = sessions[sessions.length - 1];

    if (previous && previous.key === key && start - previous.endMs <= idleThresholdMs) {
      previous.endMs = Math.max(previous.endMs, end);
      previous.eventIds.push(event.eventId);
      previous.provenance.add(event.provenance);
      continue;
    }

    sessions.push({
      key,
      tenantId: event.tenantId,
      actorId: event.actorId,
      projectId: event.projectId,
      startMs: start,
      endMs: end,
      eventIds: [event.eventId],
      provenance: new Set([event.provenance]),
    });
  }

  return sessions.map((session) => Object.freeze({
    tenantId: session.tenantId,
    actorId: session.actorId,
    projectId: session.projectId,
    startedAt: new Date(session.startMs).toISOString(),
    endedAt: new Date(session.endMs).toISOString(),
    activeMs: Math.max(0, session.endMs - session.startMs),
    eventIds: Object.freeze([...session.eventIds]),
    provenance: Object.freeze([...session.provenance].sort()),
  }));
}

export function unionActiveMs(events, { actorType = null } = {}) {
  const normalized = dedupeProductivityEvents(events)
    .map(createProductivityEvent)
    .filter((event) => !actorType || event.actorType === actorType);

  const byActor = new Map();
  for (const event of normalized) {
    const key = [event.tenantId, event.actorType, event.actorId, event.projectId ?? ''].join('|');
    const intervals = byActor.get(key) ?? [];
    intervals.push({ start: Date.parse(event.startedAt), end: Date.parse(event.endedAt) });
    byActor.set(key, intervals);
  }

  let total = 0;
  for (const intervals of byActor.values()) {
    for (const interval of mergeIntervals(intervals)) total += Math.max(0, interval.end - interval.start);
  }
  return total;
}

export function productivityKpiPrimitives(events) {
  const normalized = dedupeProductivityEvents(events);
  const humanActiveMs = unionActiveMs(normalized, { actorType: 'human' });
  const agentActiveMs = unionActiveMs(normalized, { actorType: 'agent' });
  const byProvenance = Object.create(null);
  for (const event of normalized) {
    byProvenance[event.provenance] = (byProvenance[event.provenance] ?? 0) + eventDurationMs(event);
  }

  return Object.freeze({
    eventCount: normalized.length,
    humanActiveMs,
    agentActiveMs,
    humanAgentRatio: agentActiveMs > 0 ? humanActiveMs / agentActiveMs : null,
    byProvenance: Object.freeze({ ...byProvenance }),
  });
}
