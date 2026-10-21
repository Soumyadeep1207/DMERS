import { describe, expect, it } from 'vitest';
import { toCellGrid } from './gridAdapter.js';

describe('gridAdapter', () => {
  it('converts normal, blocked and weighted-road numeric cells', () => {
    const cells = toCellGrid([[1, -1, 2.5]])[0];
    expect(cells[0]).toEqual({ base: 1, terrainWeight: 1, hazard: 0, exposure: 0, blocked: false });
    expect(cells[1]).toEqual({ base: 1, terrainWeight: 1, hazard: 0, exposure: 0, blocked: true });
    expect(cells[2]).toEqual({ base: 1, terrainWeight: 2.5, hazard: 0, exposure: 0, blocked: false });
  });
  it('does not mutate the source grid', () => {
    const numeric = [[1, -1]];
    const before = structuredClone(numeric);
    toCellGrid(numeric);
    expect(numeric).toEqual(before);
  });
});
