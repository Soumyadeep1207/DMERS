import { describe, expect, it } from 'vitest';
import { makeAdvisory, recorded } from './advisory.js';
import { ROUTE_POLICIES, choosePolicy, cellCost, HIGH_HAZARD } from './policies.js';
import { admissibleHeuristic, search } from './search.js';
import { applyScenario } from './scenario.js';
import { planMultiTarget } from './multitarget.js';
import { incidentAdvisory, matchHospitals, rankTeams } from './triage.js';
import { routeAdvisory } from './routeAdvisory.js';

const clock = () => '2026-10-22T00:00:00.000Z';
const asOf = '2026-10-22T00:00:00.000Z';
const grid = [
  [{ base: 1, terrainWeight: 1, hazard: 0, exposure: 0 }, { base: 1, terrainWeight: 1, hazard: 1, exposure: 0 }, { base: 1, terrainWeight: 1, hazard: 0, exposure: 0 }],
  [{ base: 1, terrainWeight: 1, hazard: 0, exposure: 0 }, { base: 1, terrainWeight: 1, hazard: 0, exposure: 0, blocked: true }, { base: 1, terrainWeight: 1, hazard: 0, exposure: 0 }],
  [{ base: 1, terrainWeight: 1, hazard: 0, exposure: 0 }, { base: 1, terrainWeight: 1, hazard: 0, exposure: 0 }, { base: 1, terrainWeight: 1, hazard: 0, exposure: 0 }],
];

describe('advisory envelope', () => {
  it('requires complete deterministic data', () => {
    const item = makeAdvisory({ kind: 'ROUTE', subject: 'x', recommendation: 'Review', score: .5, evidence: [recorded('test', 1, .5, .5, 'x', asOf)], limitations: ['review'], clock });
    expect(item.requiresHumanAction).toBe(true); expect(item.generatedAt).toBe(clock());
  });
  it('rejects invalid contribution totals', () => expect(() => makeAdvisory({ kind: 'ROUTE', subject: 'x', recommendation: 'x', score: .5, evidence: [recorded('x', 1, 1, .4, 'x', asOf)], limitations: ['x'], clock })).toThrow());
});

describe('policies and search', () => {
  it('freezes weights and costs differ', () => { expect(Object.isFrozen(ROUTE_POLICIES.fastest)).toBe(true); expect(new Set(Object.keys(ROUTE_POLICIES).map(p => cellCost(grid[0][1], p))).size).toBe(3); });
  it.each([[.8, 3, 3, 'HIGH', 'R1'], [.1, 0, 1, 'HIGH', 'R2'], [.1, 2, 1, 'CRITICAL', 'R3'], [.1, 2, 1, 'HIGH', 'R4']])('fires each automatic rule', (hazardLevel, availableUnits, targetCount, severity, rule) => expect(choosePolicy({ hazardLevel, availableUnits, targetCount, severity, asOf, clock }).evidence[0].source).toBe(rule));
  it('returns the full contract and never crosses a block', () => {
    for (const algorithm of ['bfs', 'dfs', 'ucs', 'greedy', 'astar']) { const result = search(grid, [0, 0], [2, 2], algorithm, 'fastest'); expect(result.status).toBe('FOUND'); expect(result.path).not.toContainEqual([1, 1]); expect(result).toEqual(expect.objectContaining({ cost: expect.any(Number), distanceUnits: expect.any(Number), riskScore: expect.any(Number), nodesExplored: expect.any(Number) })); }
  });
  it('makes UCS and A* agree and reports unreachable paths honestly', () => {
    const ucs = search(grid, [0, 0], [2, 2], 'ucs'); const astar = search(grid, [0, 0], [2, 2], 'astar'); expect(astar.cost).toBe(ucs.cost); expect(astar.nodesExplored).toBeLessThanOrEqual(ucs.nodesExplored); expect(admissibleHeuristic(grid, [0, 0], [2, 2])).toBeLessThanOrEqual(ucs.cost);
    const blocked = grid.map(row => row.map(cell => ({ ...cell, blocked: true }))); blocked[0][0].blocked = false; expect(search(blocked, [0, 0], [2, 2]).path).toBeNull();
  });
});

describe('scenario and multi-target', () => {
  it('is seeded, immutable and never reopens a block', () => { const before = structuredClone(grid); const output = applyScenario(grid, { type: 'flood', epicentre: [0, 0], seed: 12 }); expect(output).toEqual(applyScenario(grid, { type: 'flood', epicentre: [0, 0], seed: 12 })); expect(grid).toEqual(before); expect(output[1][1].blocked).toBe(true); expect(() => applyScenario(grid, { type: 'wind', epicentre: [0, 0], seed: 1 })).toThrow('wind'); });
  it('serves reachable targets and lists unreachable targets', () => { const plan = planMultiTarget(grid, [0, 0], [{ id: 'p', type: 'PICKUP', point: [0, 2] }, { id: 'h', type: 'HANDOFF', point: [2, 2] }, { id: 'bad', type: 'PICKUP', point: [1, 1] }]); expect(plan.legs.map(x => x.type)).toEqual(['PICKUP', 'HANDOFF']); expect(plan.unreachable.map(x => x.id)).toContain('bad'); expect(plan.alternatives).toHaveLength(2); });
});

describe('triage', () => {
  it('uses stated triage weights and team-id tie breaking', () => { expect(incidentAdvisory({ id: 'i', severity: 'HIGH', status: 'RESPONDING', asOf }, { clock }).score).toBeCloseTo(.45); const teams = rankTeams([{ id: 'b', name: 'B', capabilities: ['medical'], availability: 1, assigned: 0, capacity: 1, asOf }, { id: 'a', name: 'A', capabilities: ['medical'], availability: 1, assigned: 0, capacity: 1, asOf }], 'medical', { clock }); expect(teams.map(x => x.subject)).toEqual(['a', 'b']); });
  it('excludes full hospitals and labels stale capacity', () => { const result = matchHospitals([{ id: 'bad', name: 'Bad', beds_available: 0, receivingStatus: 'ACCEPTING', asOf }, { id: 'good', name: 'Good', beds_available: 2, receivingStatus: 'ACCEPTING', asOf: '2026-10-21T00:00:00.000Z' }], () => 2, { now: Date.parse('2026-10-22T01:00:00.000Z'), clock }); expect(result).toHaveLength(1); expect(result[0].limitations.join(' ')).toContain('stale'); });
  it('matches a hand-worked incident score (CRITICAL/REPORTED = 1.0)', () => { expect(incidentAdvisory({ id: 'i2', severity: 'CRITICAL', status: 'REPORTED', asOf }, { clock }).score).toBeCloseTo(1); expect(incidentAdvisory({ id: 'i3', severity: 'LOW', status: 'RESOLVED', asOf }, { clock }).score).toBeCloseTo(0); });
  it('throws on unknown severity or status instead of defaulting', () => { expect(() => incidentAdvisory({ id: 'x', severity: 'EXTREME', status: 'REPORTED', asOf }, { clock })).toThrow(); expect(() => incidentAdvisory({ id: 'x', severity: 'LOW', status: 'UNKNOWN', asOf }, { clock })).toThrow(); });
  it('splits severity weight and status factor into separate evidence rows that still sum to the score', () => { const item = incidentAdvisory({ id: 'i', severity: 'HIGH', status: 'RESPONDING', asOf }, { clock }); expect(item.evidence).toHaveLength(2); expect(item.evidence[0].factor).toMatch(/severity/i); expect(item.evidence[1].factor).toMatch(/status/i); expect(item.evidence[0].contribution + item.evidence[1].contribution).toBeCloseTo(item.score); });
  it('team-ranking contributions sum to the score and workload headroom is clamped for zero capacity', () => {
    const teams = rankTeams([{ id: 't1', name: 'T1', capabilities: ['medical'], availability: 1, assigned: 0, capacity: 0, asOf }], 'medical', { clock });
    const [item] = teams;
    expect(item.evidence.reduce((total, row) => total + row.contribution, 0)).toBeCloseTo(item.score, 9);
    expect(item.evidence.find(row => row.factor === 'Workload headroom').value).toBeGreaterThanOrEqual(0);
    expect(item.evidence.find(row => row.factor === 'Workload headroom').value).toBeLessThanOrEqual(1);
  });
  it('excludes hospitals that are not accepting transfers even with free beds', () => {
    const result = matchHospitals([{ id: 'closed', name: 'Closed', beds_available: 5, receivingStatus: 'DIVERTING', asOf }], () => 1, { now: Date.parse(asOf), clock });
    expect(result).toHaveLength(0);
  });
  it('orders qualifying hospitals by route cost under the active policy, not a weighted score', () => {
    const hospitals = [{ id: 'far', name: 'Far', beds_available: 1, receivingStatus: 'ACCEPTING', asOf }, { id: 'near', name: 'Near', beds_available: 1, receivingStatus: 'ACCEPTING', asOf }];
    const routeCost = h => (h.id === 'near' ? 1 : 9);
    const result = matchHospitals(hospitals, routeCost, { now: Date.parse(asOf), clock });
    expect(result.map(x => x.subject)).toEqual(['near', 'far']);
    expect(result.every(item => item.score === null)).toBe(true);
  });
  it('discloses missing capacity timestamps instead of assuming freshness', () => {
    const result = matchHospitals([{ id: 'h', name: 'H', beds_available: 1, receivingStatus: 'ACCEPTING' }], () => 1, { now: Date.parse(asOf), clock });
    expect(result[0].limitations.join(' ')).toContain('missing');
  });
  it('never mutates the incidents, teams or hospitals passed in', () => {
    const incident = { id: 'i', severity: 'HIGH', status: 'REPORTED', asOf }; const before = structuredClone(incident);
    incidentAdvisory(incident, { clock }); expect(incident).toEqual(before);
    const teams = [{ id: 't', name: 'T', capabilities: ['medical'], availability: 1, assigned: 0, capacity: 1, asOf }]; const teamsBefore = structuredClone(teams);
    rankTeams(teams, 'medical', { clock }); expect(teams).toEqual(teamsBefore);
  });
});

describe('automatic policy evidence', () => {
  it('records the rule explanation, triggering values and threshold', () => {
    const item = choosePolicy({ hazardLevel: .8, availableUnits: 3, targetCount: 3, severity: 'HIGH', asOf, clock });
    expect(item.recommendation).toBe('safer');
    expect(item.evidence.some(row => row.factor === 'Rule explanation')).toBe(true);
    expect(item.evidence[0].value).toMatchObject({ hazardLevel: .8, threshold: HIGH_HAZARD });
  });
  it('lists the non-selected policies and their weights', () => {
    const item = choosePolicy({ hazardLevel: .1, availableUnits: 2, targetCount: 1, severity: 'HIGH', asOf, clock });
    const alternativeFactors = item.evidence.filter(row => row.factor.startsWith('Alternative:')).map(row => row.factor);
    expect(alternativeFactors).toHaveLength(2);
  });
  it('is deterministic: identical inputs select the same policy', () => {
    const a = choosePolicy({ hazardLevel: .2, availableUnits: 4, targetCount: 2, severity: 'LOW', asOf, clock });
    const b = choosePolicy({ hazardLevel: .2, availableUnits: 4, targetCount: 2, severity: 'LOW', asOf, clock });
    expect(a.recommendation).toBe(b.recommendation);
  });
  it('handles missing inputs honestly instead of fabricating values', () => {
    expect(() => choosePolicy({ availableUnits: 1, targetCount: 1, asOf, clock })).toThrow();
  });
});

describe('search algorithm contract', () => {
  it('only claims optimal where the algorithm contract supports it', () => {
    for (const algorithm of ['bfs', 'dfs', 'greedy']) expect(search(grid, [0, 0], [2, 2], algorithm, 'fastest').optimal).toBe(false);
    for (const algorithm of ['ucs', 'astar']) expect(search(grid, [0, 0], [2, 2], algorithm, 'fastest').optimal).toBe(true);
  });
  it('heuristic never overestimates the true remaining cost to any reachable cell', () => {
    for (let r = 0; r < grid.length; r += 1) for (let c = 0; c < grid[r].length; c += 1) {
      if (!passableCell(grid, r, c)) continue;
      const trueCost = search(grid, [r, c], [2, 2], 'ucs', 'fastest');
      if (trueCost.status !== 'FOUND') continue;
      expect(admissibleHeuristic(grid, [r, c], [2, 2])).toBeLessThanOrEqual(trueCost.cost + 1e-9);
    }
  });
  it('never returns a silent partial route for an unreachable target', () => {
    for (const algorithm of ['bfs', 'dfs', 'ucs', 'greedy', 'astar']) {
      const blocked = grid.map(row => row.map(cell => ({ ...cell, blocked: true }))); blocked[0][0].blocked = false;
      const result = search(blocked, [0, 0], [2, 2], algorithm, 'fastest');
      expect(result.status).toBe('UNREACHABLE'); expect(result.path).toBeNull();
    }
  });
});

describe('multi-target detail', () => {
  it('connects consecutive legs and keeps totals consistent with the legs', () => {
    const plan = planMultiTarget(grid, [0, 0], [{ id: 'p', type: 'PICKUP', point: [0, 2] }, { id: 'h', type: 'HANDOFF', point: [2, 2] }]);
    for (let i = 1; i < plan.legs.length; i += 1) expect(plan.legs[i].start).toEqual(plan.legs[i - 1].end);
    expect(plan.totalCost).toBeCloseTo(plan.legs.reduce((total, leg) => total + leg.cost, 0));
    expect(plan.totalDistanceUnits).toBe(plan.legs.reduce((total, leg) => total + leg.distanceUnits, 0));
  });
  it('alternatives carry full route detail, not just totals', () => {
    const plan = planMultiTarget(grid, [0, 0], [{ id: 'p', type: 'PICKUP', point: [0, 2] }]);
    for (const alt of plan.alternatives) {
      expect(alt).toHaveProperty('policy'); expect(alt).toHaveProperty('status'); expect(alt).toHaveProperty('legs');
      expect(alt).toHaveProperty('risk'); expect(alt.evidence.length).toBeGreaterThan(0); expect(alt.limitations.length).toBeGreaterThan(0);
    }
  });
  it('states the greedy-heuristic limitation, never claiming a globally optimal tour', () => {
    const plan = planMultiTarget(grid, [0, 0], [{ id: 'p', type: 'PICKUP', point: [0, 2] }]);
    expect(plan.limitations.join(' ')).toMatch(/greedy/i);
  });
});

describe('scenario degradation', () => {
  it('never reduces traversal cost for a comparable cell', () => {
    const before = grid[0][1];
    const after = applyScenario(grid, { type: 'fire', epicentre: [0, 1], seed: 7 })[0][1];
    expect(after.hazard).toBeGreaterThanOrEqual(before.hazard);
    expect(after.terrainWeight).toBeGreaterThanOrEqual(before.terrainWeight);
  });
});

describe('accountability', () => {
  it('advisories never report a non-null score outside [0,1]', () => {
    expect(() => makeAdvisory({ kind: 'TRIAGE', subject: 'x', recommendation: 'x', score: 1.5, evidence: [recorded('x', 1, 1, 1.5, 'x', asOf)], limitations: ['x'], clock })).toThrow();
  });
  it('requiresHumanAction is always true across every advisory kind', () => {
    const policy = choosePolicy({ hazardLevel: .1, availableUnits: 2, targetCount: 1, severity: 'LOW', asOf, clock });
    const incident = incidentAdvisory({ id: 'i', severity: 'LOW', status: 'REPORTED', asOf }, { clock });
    const [team] = rankTeams([{ id: 't', name: 'T', capabilities: ['medical'], availability: 1, assigned: 0, capacity: 1, asOf }], 'medical', { clock });
    const [hospital] = matchHospitals([{ id: 'h', name: 'H', beds_available: 1, receivingStatus: 'ACCEPTING', asOf }], () => 1, { now: Date.parse(asOf), clock });
    for (const item of [policy, incident, team, hospital]) expect(item.requiresHumanAction).toBe(true);
  });
});

function passableCell(cellGrid, r, c) { return cellGrid[r]?.[c] && !cellGrid[r][c].blocked; }

describe('route advisory', () => {
  it('wraps a found route with evidence and limitations, score null', () => {
    const result = search(grid, [0, 0], [2, 2], 'astar', 'balanced');
    const item = routeAdvisory(result, { algorithm: 'astar', policy: 'balanced', clock });
    expect(item.kind).toBe('ROUTE'); expect(item.score).toBeNull(); expect(item.requiresHumanAction).toBe(true);
    expect(item.evidence.some(row => row.factor === 'Cost (grid units)')).toBe(true);
    expect(item.limitations.join(' ')).toMatch(/not measured travel time/);
  });
  it('still reports evidence honestly for an unreachable route', () => {
    const blocked = grid.map(row => row.map(cell => ({ ...cell, blocked: true }))); blocked[0][0].blocked = false;
    const result = search(blocked, [0, 0], [2, 2], 'astar', 'balanced');
    const item = routeAdvisory(result, { algorithm: 'astar', policy: 'balanced', clock });
    expect(item.recommendation).toMatch(/no route/i);
  });
  it('rejects an unknown policy instead of silently defaulting', () => {
    expect(() => routeAdvisory({ status: 'FOUND' }, { algorithm: 'astar', policy: 'nope', clock })).toThrow();
  });
});
