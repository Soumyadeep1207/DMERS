import { makeAdvisory, recorded } from './advisory.js';

export const SEVERITY_WEIGHT = Object.freeze({ CRITICAL: 1, HIGH: 0.75, MODERATE: 0.5, LOW: 0.25 });
export const STATUS_FACTOR = Object.freeze({ REPORTED: 1, VERIFIED: 1, RESPONDING: 0.6, RESOLVED: 0 });
export const STALE_BED_THRESHOLD_MS = 30 * 60 * 1000;
const mandatory = ['Rules-based advisory, not a trained model.', 'Route costs are grid units; no live traffic is included.', 'Capacity and availability are as recorded.', 'Requires review by an authorized person.'];
const clamp = value => Math.max(0, Math.min(1, value));

/**
 * Incident score is severityWeight * statusFactor, a product rather than a
 * weighted sum. The first evidence row carries the whole score so the
 * envelope's contribution-sum check holds; the second row is informational
 * (contribution 0) so the status factor's own value stays visible.
 */
export function incidentAdvisory(incident, { clock }) {
  const severityWeight = SEVERITY_WEIGHT[incident.severity], statusFactor = STATUS_FACTOR[incident.status];
  if (severityWeight === undefined || statusFactor === undefined) throw new Error('Unknown incident severity or status');
  const score = severityWeight * statusFactor;
  return makeAdvisory({
    kind: 'TRIAGE', subject: incident.id, recommendation: 'Review incident priority', score,
    evidence: [
      recorded('Severity weight', incident.severity, severityWeight, score, 'severity', incident.asOf),
      recorded('Status factor', incident.status, statusFactor, 0, 'status', incident.asOf),
    ],
    limitations: mandatory, inputs: incident, seed: null, clock,
  });
}

export function rankTeams(teams, requirement, { clock }) {
  const scored = teams.map(team => {
    const capabilityMatch = clamp(team.capabilities.includes(requirement) ? 1 : 0);
    const availability = clamp(team.availability);
    const workloadHeadroom = clamp(1 - team.assigned / Math.max(1, team.capacity));
    const score = 0.5 * capabilityMatch + 0.3 * availability + 0.2 * workloadHeadroom;
    return {
      team, score,
      evidence: [
        recorded('Capability match', capabilityMatch, 0.5, 0.5 * capabilityMatch, 'capabilities', team.asOf),
        recorded('Availability', availability, 0.3, 0.3 * availability, 'availability', team.asOf),
        recorded('Workload headroom', workloadHeadroom, 0.2, 0.2 * workloadHeadroom, 'assigned/capacity', team.asOf),
      ],
    };
  }).sort((a, b) => b.score - a.score || String(a.team.id).localeCompare(String(b.team.id), undefined, { numeric: true }));
  return scored.map(item => makeAdvisory({ kind: 'TEAM_RANKING', subject: item.team.id, recommendation: `Consider ${item.team.name}`, score: item.score, evidence: item.evidence, limitations: mandatory, inputs: { requirement, team: item.team }, seed: null, clock }));
}

/**
 * Hospital matching is an eligibility filter (free beds + accepting transfers),
 * ordered by route cost under the active policy. It is not a weighted
 * prediction score, so `score` stays null and no contribution-sum applies.
 */
export function matchHospitals(hospitals, routeCost, { now, clock }) {
  const eligible = hospitals.filter(h => h.beds_available >= 1 && h.receivingStatus === 'ACCEPTING');
  const withCost = eligible.map(hospital => ({ hospital, cost: routeCost(hospital) })).sort((a, b) => a.cost - b.cost);
  return withCost.map(({ hospital, cost }) => {
    const hasTimestamp = Boolean(hospital.asOf);
    const age = hasTimestamp ? now - new Date(hospital.asOf).getTime() : null;
    const limitations = [...mandatory, 'Eligibility is beds-available and accepting-transfers only; ordering reflects route cost under the active policy, not a weighted prediction score.'];
    if (!hasTimestamp) limitations.push('Capacity timestamp is missing; freshness cannot be verified.');
    else if (age > STALE_BED_THRESHOLD_MS) limitations.push(`Recorded bed availability is ${age} ms old and may be stale (freshness threshold ${STALE_BED_THRESHOLD_MS} ms).`);
    return makeAdvisory({
      kind: 'HOSPITAL_MATCH', subject: hospital.id, recommendation: `Consider ${hospital.name}`, score: null,
      evidence: [
        recorded('Recorded free beds', hospital.beds_available, null, null, 'beds_available', hospital.asOf ?? null),
        recorded('Receiving status', hospital.receivingStatus, null, null, 'receivingStatus', hospital.asOf ?? null),
        recorded('Route cost (ordering key, active policy)', cost, null, null, 'route-cost', clock()),
      ],
      limitations, inputs: hospital, seed: null, clock,
    });
  });
}
