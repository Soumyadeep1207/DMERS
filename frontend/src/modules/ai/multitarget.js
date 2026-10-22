import { search } from './search.js';
import { ROUTE_POLICIES } from './policies.js';

function planCore(grid, start, targets, policy) {
  let current = start, remaining = [...targets], totalCost = 0, totalDistanceUnits = 0, totalRisk = 0;
  const legs = [], unreachable = [];
  while (remaining.length) {
    const candidates = remaining
      .map(target => ({ target, result: search(grid, current, target.point, 'astar', policy) }))
      .filter(item => item.result.status === 'FOUND');
    if (!candidates.length) { unreachable.push(...remaining); break; }
    candidates.sort((a, b) => a.result.cost - b.result.cost);
    const { target, result } = candidates[0];
    legs.push({ type: target.type, target: target.id, start: current, end: target.point, ...result });
    totalCost += result.cost; totalDistanceUnits += result.distanceUnits; totalRisk += result.riskScore;
    current = target.point;
    remaining = remaining.filter(item => item !== target);
  }
  return { legs, totalCost, totalDistanceUnits, totalRisk, unreachable };
}

const GREEDY_LIMITATION = 'Multi-target ordering is a greedy nearest-reachable-target heuristic, not a globally optimal tour.';

/**
 * Nearest-reachable-target ordering under the active policy, plus up to two
 * alternatives computed under the other policies for comparison. Every
 * requested target is accounted for in either `legs` or `unreachable`.
 */
export function planMultiTarget(grid, start, targets, policy = 'balanced') {
  const primary = planCore(grid, start, targets, policy);
  const alternatives = Object.keys(ROUTE_POLICIES)
    .filter(name => name !== policy)
    .slice(0, 2)
    .map(name => {
      const plan = planCore(grid, start, targets, name);
      const status = plan.unreachable.length === targets.length ? 'UNREACHABLE' : plan.unreachable.length ? 'PARTIAL' : 'FOUND';
      return {
        policy: name, status, legs: plan.legs, cost: plan.totalCost, distanceUnits: plan.totalDistanceUnits,
        risk: plan.totalRisk, unreachable: plan.unreachable,
        evidence: [{ factor: 'Alternative policy weights', value: ROUTE_POLICIES[name], weight: null, contribution: null, source: `policy.${name}`, asOf: null }],
        limitations: [GREEDY_LIMITATION],
      };
    });
  return {
    legs: primary.legs, totalCost: primary.totalCost, totalDistanceUnits: primary.totalDistanceUnits,
    totalRisk: primary.totalRisk, unreachable: primary.unreachable, alternatives, limitations: [GREEDY_LIMITATION],
  };
}
