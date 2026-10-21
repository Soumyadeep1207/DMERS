const clone = grid => grid.map(row => row.map(cell => ({ ...cell })));
export function seededRng(seed) { let state = (Number(seed) >>> 0) || 1; return () => { state ^= state << 13; state ^= state >>> 17; state ^= state << 5; return (state >>> 0) / 2 ** 32; }; }
const severity = cell => cell.blocked ? 4 : Math.max(cell.hazard || 0, (cell.terrainWeight || 1) - 1);

/** Produces a new grid and only increases risk/terrain severity; it never reopens a cell. */
export function applyScenario(grid, { type, epicentre, seed, extraClosures = [] }) {
  if (!['flood', 'fire', 'earthquake'].includes(type)) throw new Error(`Unknown scenario type: ${type}`);
  const next = clone(grid), random = seededRng(seed), [er, ec] = epicentre;
  for (let r = 0; r < next.length; r += 1) for (let c = 0; c < next[r].length; c += 1) {
    const cell = next[r][c]; if (cell.blocked) continue;
    const distance = Math.abs(r - er) + Math.abs(c - ec); const affected = distance <= 2 || random() < 0.08;
    if (!affected) continue;
    const worsening = type === 'fire' ? 0.7 : type === 'earthquake' ? 0.5 : 0.35;
    const candidate = { ...cell, hazard: Math.max(cell.hazard || 0, worsening), terrainWeight: Math.max(cell.terrainWeight || 1, type === 'flood' ? 1.4 : 1.2) };
    next[r][c] = severity(candidate) >= severity(cell) ? candidate : cell;
  }
  for (const [r, c] of extraClosures) if (next[r]?.[c]) next[r][c] = { ...next[r][c], blocked: true };
  return next;
}
