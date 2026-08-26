import { dedupeProductivityEvents, eventDurationMs } from './productivityEvents.js';
import { productivityKpiPrimitives } from './productivitySessions.js';

export const DEFAULT_HOURLY_RATES = Object.freeze({ conservative: 15, medium: 25, strategic: 40 });

function hours(ms) { return ms / 3_600_000; }
function finite(value, fallback = 0) { const n = Number(value); return Number.isFinite(n) ? n : fallback; }

export function filterWindow(events, { now = new Date(), days = 30 } = {}) {
  const end = now instanceof Date ? now.getTime() : new Date(now).getTime();
  if (!Number.isFinite(end)) throw new TypeError('now must be a valid date');
  if (![7, 30, 90].includes(Number(days))) throw new RangeError('days must be 7, 30, or 90');
  const start = end - Number(days) * 86_400_000;
  return dedupeProductivityEvents(events).filter((event) => {
    const at = Date.parse(event.endedAt);
    return at >= start && at <= end;
  });
}

export function computeProductivityRoi(events, options = {}) {
  const scoped = filterWindow(events, options);
  const primitives = productivityKpiPrimitives(scoped);
  const rates = { ...DEFAULT_HOURLY_RATES, ...(options.hourlyRates || {}) };

  let tasksCompleted = 0;
  let commits = 0;
  let testsPass = 0;
  let testsFail = 0;
  let documents = 0;
  let automations = 0;
  let delegatedHours = 0;
  let explicitSavedHours = 0;
  let externalCostActual = 0;
  let traditionalHours = 0;
  let assistedHours = 0;
  let reworkEvents = 0;
  let successEvents = 0;

  const projects = new Map();
  for (const event of scoped) {
    const meta = event.metadata || {};
    if (event.eventType === 'task_completed') tasksCompleted += 1;
    if (event.eventType === 'commit') commits += 1;
    if (event.eventType === 'test_pass') testsPass += 1;
    if (event.eventType === 'test_fail') testsFail += 1;
    if (event.eventType === 'document_generated') documents += 1;
    if (event.eventType === 'automation') automations += 1;
    if (meta.outcome === 'success') successEvents += 1;
    if (meta.rework === true || event.eventType === 'rework') reworkEvents += 1;
    delegatedHours += finite(meta.delegatedHours);
    explicitSavedHours += finite(meta.savedHumanHours);
    externalCostActual += finite(meta.externalCostUsd);
    traditionalHours += finite(meta.traditionalHours);
    assistedHours += finite(meta.assistedHours);

    const projectId = event.projectId || 'unassigned';
    const p = projects.get(projectId) || { events: 0, tasksCompleted: 0, firstAt: null, lastAt: null };
    p.events += 1;
    if (event.eventType === 'task_completed') p.tasksCompleted += 1;
    const start = Date.parse(event.startedAt);
    const end = Date.parse(event.endedAt);
    p.firstAt = p.firstAt == null ? start : Math.min(p.firstAt, start);
    p.lastAt = p.lastAt == null ? end : Math.max(p.lastAt, end);
    projects.set(projectId, p);
  }

  const humanHours = hours(primitives.humanActiveMs);
  const agentHours = hours(primitives.agentActiveMs);
  const hoursSaved = Math.max(0, explicitSavedHours || (traditionalHours > 0 ? traditionalHours - assistedHours : 0));
  const avoidedByRate = Object.fromEntries(Object.entries(rates).map(([name, rate]) => [name, hoursSaved * finite(rate)]));
  const valueRecovered = Object.fromEntries(Object.entries(rates).map(([name, rate]) => [name, hoursSaved * finite(rate) - externalCostActual]));
  const roi = Object.fromEntries(Object.entries(rates).map(([name]) => [name, externalCostActual > 0 ? valueRecovered[name] / externalCostActual : null]));

  const projectThroughput = Object.fromEntries([...projects.entries()].map(([id, p]) => [id, {
    events: p.events,
    tasksCompleted: p.tasksCompleted,
    leadTimeHours: p.firstAt == null || p.lastAt == null ? null : hours(p.lastAt - p.firstAt),
  }]));

  const outcomes = successEvents + reworkEvents;
  return Object.freeze({
    windowDays: Number(options.days || 30),
    eventCount: scoped.length,
    humanActiveHours: humanHours,
    agentActiveHours: agentHours,
    humanAgentRatio: primitives.humanAgentRatio,
    tasksCompleted, commits, testsPass, testsFail, documentsGenerated: documents, automations,
    delegatedHours,
    hoursSaved,
    externalCostActual,
    externalCostAvoided: avoidedByRate,
    valueRecovered,
    roi,
    successRate: outcomes ? successEvents / outcomes : null,
    reworkRate: outcomes ? reworkEvents / outcomes : null,
    projectThroughput,
    provenanceMs: primitives.byProvenance,
  });
}

export function adaptOpsTask(task, { tenantId = 'innerchispa', actorId = 'ralfia' } = {}) {
  if (!task?.task_id || !task?.created_at) return null;
  const completed = task.status === 'completed' || task.status === 'done';
  return {
    eventId: `ops:${task.task_id}:${task.status || 'unknown'}`,
    tenantId,
    projectId: task.related_project || null,
    taskId: task.task_id,
    actorType: task.owner?.startsWith?.('AG-') || task.assignee?.startsWith?.('AG-') ? 'agent' : 'system',
    actorId: task.owner || task.assignee || actorId,
    eventType: completed ? 'task_completed' : 'task_state',
    source: 'ops_tasks',
    provenance: 'measured',
    startedAt: task.created_at,
    endedAt: task.updated_at || task.created_at,
    evidenceRef: task.task_id,
    metadata: { status: task.status, priority: task.priority },
  };
}

export function adaptGitCommit(commit, { tenantId = 'innerchispa', projectId = null } = {}) {
  if (!commit?.sha || !commit?.timestamp) return null;
  return {
    eventId: `git:${commit.sha}`,
    tenantId,
    projectId,
    taskId: commit.taskId || null,
    actorType: commit.actorType || 'human',
    actorId: commit.author || 'unknown',
    eventType: 'commit',
    source: 'git',
    provenance: 'measured',
    startedAt: commit.timestamp,
    endedAt: commit.timestamp,
    evidenceRef: commit.sha,
    metadata: { message: commit.message || '' },
  };
}

export function mergeBackfill({ existing = [], incoming = [] } = {}) {
  return dedupeProductivityEvents([...existing, ...incoming.filter(Boolean)]);
}
