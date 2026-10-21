import { makeAdvisory, recorded } from './advisory.js';

export const ROUTE_POLICIES = Object.freeze({
  fastest: Object.freeze({ w_distance: 1, w_risk: 0 }),
  balanced: Object.freeze({ w_distance: 1, w_risk: 0.5 }),
  safer: Object.freeze({ w_distance: 1, w_risk: 1.5 }),
});
export const HIGH_HAZARD = 0.7;
const RULE_EXPLANATION = Object.freeze({
  R1: 'Hazard level at or above the high-hazard threshold.',
  R2: 'Fewer available units than targets (scarcity below 1).',
  R3: 'Incident severity is CRITICAL.',
  R4: 'No higher-priority rule matched; default policy.',
});

export function cellCost(cell, policy) {
  const weights = ROUTE_POLICIES[policy];
  if (!weights) throw new Error(`Unknown route policy: ${policy}`);
  return weights.w_distance * cell.base * cell.terrainWeight + weights.w_risk * (cell.hazard + cell.exposure);
}

/**
 * R1-R4 evaluated in order; score stays null because policy choice is a rule
 * lookup, not a weighted sum. Evidence rows are informational (contribution
 * null) rather than pretending to add up to a score.
 */
export function choosePolicy({ hazardLevel, availableUnits, targetCount, severity, asOf, clock }) {
  if (hazardLevel == null || availableUnits == null || targetCount == null) {
    throw new Error('choosePolicy requires hazardLevel, availableUnits and targetCount');
  }
  const scarcity = availableUnits / Math.max(1, targetCount);
  const [policy, rule] = hazardLevel >= HIGH_HAZARD ? ['safer', 'R1']
    : scarcity < 1 ? ['fastest', 'R2'] : severity === 'CRITICAL' ? ['fastest', 'R3'] : ['balanced', 'R4'];
  const weights = ROUTE_POLICIES[policy];
  const evidence = [
    recorded(`Automatic policy ${rule}`, { hazardLevel, scarcity, severity, threshold: HIGH_HAZARD }, 0, 0, rule, asOf),
    recorded('Rule explanation', RULE_EXPLANATION[rule], null, null, rule, asOf),
    recorded('Selected policy weights', weights, null, null, `policy.${policy}`, asOf),
    ...Object.entries(ROUTE_POLICIES).filter(([name]) => name !== policy).map(([name, w]) => recorded(`Alternative: ${name}`, w, null, null, `policy.${name}`, asOf)),
  ];
  return makeAdvisory({
    kind: 'POLICY', subject: 'route-policy', recommendation: policy, score: null,
    evidence,
    limitations: ['Rules-based policy selection; review current conditions before acting.', 'Hazard level is the corridor-mean value supplied at decision time, not live sensor data.'],
    inputs: { hazardLevel, availableUnits, targetCount, severity, weights }, seed: null, clock,
  });
}
