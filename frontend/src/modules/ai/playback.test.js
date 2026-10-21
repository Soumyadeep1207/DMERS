import { describe, expect, it } from 'vitest';
import { createPlayback, currentCell, traversedCells, step, isComplete, accumulatedCost } from './playback.js';

const grid = [
  [{ base: 1, terrainWeight: 1, hazard: 0, exposure: 0 }, { base: 1, terrainWeight: 1, hazard: 0, exposure: 0 }],
  [{ base: 1, terrainWeight: 1, hazard: 0, exposure: 0 }, { base: 1, terrainWeight: 1, hazard: 0, exposure: 0 }],
];
const route = { path: [[0, 0], [0, 1], [1, 1]], cost: 2, distanceUnits: 2, riskScore: 0, nodesExplored: 3, optimal: true, status: 'FOUND' };

describe('playback', () => {
  it('reports an invalid route explicitly instead of silently doing nothing', () => {
    const state = createPlayback({ path: [], status: 'FOUND' });
    expect(state.status).toBe('INVALID');
    expect(currentCell(state)).toBeNull();
    expect(traversedCells(state)).toEqual([]);
    expect(accumulatedCost(state, grid, 'fastest')).toBeNull();
    expect(step(state)).toBe(state);
  });
  it('replays an already-computed route one cell at a time without recomputing it', () => {
    let state = createPlayback(route);
    expect(state.status).toBe('READY');
    expect(currentCell(state)).toEqual([0, 0]);
    expect(isComplete(state)).toBe(false);
    state = step(state);
    expect(currentCell(state)).toEqual([0, 1]);
    expect(traversedCells(state)).toEqual([[0, 0], [0, 1]]);
    expect(accumulatedCost(state, grid, 'fastest')).toBeCloseTo(1);
    state = step(state);
    expect(isComplete(state)).toBe(true);
    expect(accumulatedCost(state, grid, 'fastest')).toBeCloseTo(2);
    const stepped = step(state);
    expect(stepped).toBe(state);
  });
  it('treats the route as immutable input (same object, never mutated)', () => {
    const before = structuredClone(route);
    const state = step(createPlayback(route));
    expect(route).toEqual(before);
    expect(state.route).toBe(route);
  });
});
