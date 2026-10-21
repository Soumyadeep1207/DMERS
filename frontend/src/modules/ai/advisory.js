/** Pure advisory envelope. `clock` is injected so output is reproducible. */
export const ADVISORY_KINDS = Object.freeze(['ROUTE', 'POLICY', 'TEAM_RANKING', 'HOSPITAL_MATCH', 'TRIAGE']);

export function makeAdvisory({ kind, subject, recommendation, score = null, evidence, limitations, inputs = {}, seed = null, clock }) {
  if (!ADVISORY_KINDS.includes(kind)) throw new Error(`Unknown advisory kind: ${kind}`);
  if (!Array.isArray(evidence) || evidence.length === 0) throw new Error('Advisory evidence must not be empty');
  if (!Array.isArray(limitations) || limitations.length === 0) throw new Error('Advisory limitations must not be empty');
  if (score !== null && (score < 0 || score > 1)) throw new Error('Advisory score must be in [0,1] or null');
  const contribution = evidence.reduce((total, item) => total + Number(item.contribution || 0), 0);
  if (score !== null && Math.abs(contribution - score) > 1e-9) throw new Error('Evidence contributions must sum to score');
  return { kind, subject, recommendation, score, evidence, limitations, inputs, seed, generatedAt: clock(), requiresHumanAction: true };
}

export const recorded = (factor, value, weight, contribution, source, asOf) => ({ factor, value, weight, contribution, source, asOf });
