import { describe, expect, it } from 'vitest';
import { makeAdvisory, recorded } from './advisory.js';
import { ROUTE_POLICIES, choosePolicy, cellCost } from './policies.js';
import { admissibleHeuristic, search } from './search.js';
import { applyScenario } from './scenario.js';
import { planMultiTarget } from './multitarget.js';
import { incidentAdvisory, matchHospitals, rankTeams } from './triage.js';

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
});
