import { makeAdvisory, recorded } from './advisory.js';
import { ROUTE_POLICIES } from './policies.js';

const LIMITATIONS = [
  'Route costs are grid-cost units, not measured travel time; no live traffic or verified road condition is used.',
  'Optimal is claimed only for the grid-cost objective under the active policy, not for real-world travel time.',
  'Requires review by an authorized person before any dispatch decision.',
];

/**
 * Wraps a raw search()/local-search result as a ROUTE advisory with the
 * same evidence the comparison table already shows, so a presented route
 * carries evidence/limitations like every other advisory kind (score is
 * null: a route's cost/risk/optimality are not a normalized prediction).
 */
export function routeAdvisory(result, { algorithm, policy, clock }) {
  const weights = ROUTE_POLICIES[policy];
  if (!weights) throw new Error(`Unknown route policy: ${policy}`);
  const evidence = [
    recorded('Algorithm', algorithm, null, null, 'search.algorithm', null),
    recorded('Policy weights', weights, null, null, `policy.${policy}`, null),
    recorded('Status', result.status, null, null, 'search.status', null),
  ];
  if (result.status === 'FOUND') {
    evidence.push(
      recorded('Cost (grid units)', result.cost, null, null, 'search.cost', null),
      recorded('Distance (grid units)', result.distanceUnits, null, null, 'search.distanceUnits', null),
      recorded('Risk', result.riskScore, null, null, 'search.riskScore', null),
      recorded('Nodes explored', result.nodesExplored, null, null, 'search.nodesExplored', null),
      recorded('Optimal for this cost objective', result.optimal, null, null, 'search.optimal', null),
    );
  }
  return makeAdvisory({
    kind: 'ROUTE', subject: `${algorithm}/${policy}`, recommendation: result.status === 'FOUND' ? 'Review proposed route' : 'No route available under current conditions',
    score: null, evidence, limitations: LIMITATIONS, inputs: { algorithm, policy }, seed: null, clock,
  });
}
