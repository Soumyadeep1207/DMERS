/** Shared fixture grid/clock for the demo scripts. All output stays within 90 columns. */
export const clock = () => new Date('2026-10-22T00:00:00.000Z').toISOString();
export const asOf = clock();

const cell = (overrides = {}) => ({ base: 1, terrainWeight: 1, hazard: 0, exposure: 0, ...overrides });

/**
 * A vertical wall at column 6 can only be crossed at three rows, forcing a
 * choice between three lanes with different distance/risk trade-offs:
 *   - row 1  (short, very hazardous): the direct line between origin and
 *     target, carrying four heavily-hazardous cells.
 *   - row 6  (medium detour, lightly hazardous): one hazardous cell plus a
 *     12-unit detour away from the direct line.
 *   - row 10 (long detour, clean): zero hazard but a 18-unit detour.
 * The weights pick three different lanes: fastest ignores risk and takes the
 * shortest (row 1); safer pays the full detour to avoid risk (row 10);
 * balanced lands on the lane in between (row 6). This is a constructed
 * fixture, not a claim that every grid produces three distinct lanes.
 */
export function demoGrid() {
  const rows = 13, cols = 13, wallCol = 6;
  const grid = Array.from({ length: rows }, () => Array.from({ length: cols }, () => cell()));
  for (let r = 0; r < rows; r += 1) {
    if (r === 1 || r === 6 || r === 10) continue;
    grid[r][wallCol] = cell({ blocked: true });
  }
  for (const c of [5, 6, 7, 8]) grid[1][c] = cell({ hazard: 8, exposure: 2 });
  grid[6][wallCol] = cell({ hazard: 5, exposure: 1 });
  grid[10][wallCol] = cell();
  return grid;
}

export const ORIGIN = [1, 0];
export const TARGET = [1, 12];
