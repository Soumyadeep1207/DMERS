import { bankerSafeSequence, evaluateBankerRequest } from '../../osAlgorithms.js';

export { bankerSafeSequence, evaluateBankerRequest };

export const COFFMAN_CONDITIONS = [
  { id: 'mutualExclusion', label: 'Mutual exclusion', meaning: 'At least one resource is held in a non-shareable mode.' },
  { id: 'holdAndWait', label: 'Hold and wait', meaning: 'A process holds resources while requesting additional resources.' },
  { id: 'noPreemption', label: 'No preemption', meaning: 'Resources cannot be forcibly taken; holders release them voluntarily.' },
  { id: 'circularWait', label: 'Circular wait', meaning: 'A cycle of processes waits for resources held by the next process.' },
];

export function detectWaitForCycles(edges) {
  const graph = new Map();
  for (const [from, to] of edges) graph.set(from, [...(graph.get(from) || []), to]);
  const visiting = new Set(), visited = new Set(), cycles = [];
  function visit(node, path) {
    if (visiting.has(node)) { const start = path.indexOf(node); if (start >= 0) cycles.push([...path.slice(start), node]); return; }
    if (visited.has(node)) return;
    visiting.add(node); for (const next of graph.get(node) || []) visit(next, [...path, node]);
    visiting.delete(node); visited.add(node);
  }
  for (const node of graph.keys()) visit(node, []);
  const unique = new Map(cycles.map(cycle => [cycle.slice(0, -1).sort().join('|'), cycle]));
  return [...unique.values()];
}

/** Multi-instance detection: Work starts at Available; unfinished P can finish when Request[P] <= Work. */
export function detectMultiInstanceDeadlock(available, allocation, outstanding) {
  const work = [...available], finished = allocation.map(row => row.every(value => value === 0));
  let changed = true;
  while (changed) {
    changed = false;
    for (let i = 0; i < allocation.length; i += 1) if (!finished[i] && outstanding[i].every((value, j) => value <= work[j])) {
      work.forEach((_, j) => { work[j] += allocation[i][j]; }); finished[i] = true; changed = true;
    }
  }
  return { deadlocked: finished.map((done, i) => done ? null : `P${i}`).filter(Boolean), work };
}

export function breakCoffmanConditions(enabled = {}) {
  return COFFMAN_CONDITIONS.map(condition => ({ ...condition, holds: enabled[condition.id] ?? true,
    prevented: !(enabled[condition.id] ?? true) }));
}

export function recoverByTermination(processes, resources) {
  // Stated teaching cost: terminate the lowest-priority task first (larger numeric value), then free more resources, then PID.
  const victim = [...processes].sort((a, b) => (b.priority ?? 5) - (a.priority ?? 5)
    || (b.resourcesHeld?.length ?? 0) - (a.resourcesHeld?.length ?? 0) || String(a.pid).localeCompare(String(b.pid)))[0];
  if (!victim) return { victim: null, resourcesAfter: [...resources], costRule: 'No process to terminate.' };
  const resourcesAfter = resources.map((value, index) => value + (victim.allocation?.[index] ?? 0));
  return { victim: victim.pid, resourcesAfter, costRule: 'Terminate lowest-priority incident first (larger priority number); tie-break by most resources released, then PID. This is a teaching heuristic, not a universal recovery policy.' };
}
