import { cellCost } from './policies.js';

const key = ([r, c]) => `${r},${c}`;
const same = (a, b) => a[0] === b[0] && a[1] === b[1];
const dirs = [[1, 0], [-1, 0], [0, 1], [0, -1]];
export const passable = cell => cell && !cell.blocked;
export const neighbours = (grid, [r, c]) => dirs.map(([dr, dc]) => [r + dr, c + dc]).filter(([nr, nc]) => passable(grid[nr]?.[nc]));

function reconstruct(parent, goal) { const path = []; for (let at = key(goal); at; at = parent.get(at)) path.unshift(at.split(',').map(Number)); return path; }
function metrics(grid, path, policy) {
  const cells = path.slice(1).map(([r, c]) => grid[r][c]);
  return { cost: cells.reduce((n, cell) => n + cellCost(cell, policy), 0), distanceUnits: cells.length, riskScore: cells.reduce((n, cell) => n + cell.hazard + cell.exposure, 0) };
}
function unreachable(nodesExplored, optimal) { return { path: null, cost: null, distanceUnits: null, riskScore: null, nodesExplored, optimal, status: 'UNREACHABLE' }; }

function depthSearch(grid, start, goal, policy, depthFirst) {
  const frontier = [start], parent = new Map([[key(start), null]]), settled = new Set(); let explored = 0;
  while (frontier.length) { const point = depthFirst ? frontier.pop() : frontier.shift(); const id = key(point); if (settled.has(id)) continue; settled.add(id); explored += 1;
    if (same(point, goal)) { const path = reconstruct(parent, goal); return { path, ...metrics(grid, path, policy), nodesExplored: explored, optimal: false, status: 'FOUND' }; }
    for (const next of neighbours(grid, point)) if (!parent.has(key(next))) { parent.set(key(next), id); frontier.push(next); }
  } return unreachable(explored, false);
}

/** Manhattan distance multiplied by the minimum passable distance-only step cost is admissible: risk is non-negative and each remaining move costs at least this amount. */
export function admissibleHeuristic(grid, point, goal) {
  const minimum = Math.min(...grid.flat().filter(passable).map(cell => cell.base * cell.terrainWeight));
  return (Math.abs(point[0] - goal[0]) + Math.abs(point[1] - goal[1])) * minimum;
}
function bestFirst(grid, start, goal, policy, heuristic, includeCost, optimal) {
  const frontier = [{ point: start, g: 0 }], parent = new Map([[key(start), null]]), best = new Map([[key(start), 0]]), settled = new Set(); let explored = 0;
  while (frontier.length) { frontier.sort((a, b) => (a.g * includeCost + heuristic(a.point, goal)) - (b.g * includeCost + heuristic(b.point, goal))); const current = frontier.shift(); const id = key(current.point);
    if (settled.has(id)) continue; settled.add(id); explored += 1;
    if (same(current.point, goal)) { const path = reconstruct(parent, goal); return { path, ...metrics(grid, path, policy), nodesExplored: explored, optimal, status: 'FOUND' }; }
    for (const next of neighbours(grid, current.point)) { const nextId = key(next), nextG = current.g + cellCost(grid[next[0]][next[1]], policy); if (nextG < (best.get(nextId) ?? Infinity)) { best.set(nextId, nextG); parent.set(nextId, id); frontier.push({ point: next, g: nextG }); } }
  } return unreachable(explored, optimal);
}
export function search(grid, start, goal, algorithm = 'astar', policy = 'balanced') {
  if (!passable(grid[start[0]]?.[start[1]]) || !passable(grid[goal[0]]?.[goal[1]])) return unreachable(0, algorithm === 'ucs' || algorithm === 'astar');
  if (algorithm === 'bfs') return depthSearch(grid, start, goal, policy, false);
  if (algorithm === 'dfs') return depthSearch(grid, start, goal, policy, true);
  if (algorithm === 'ucs') return bestFirst(grid, start, goal, policy, () => 0, true, true);
  if (algorithm === 'greedy') return bestFirst(grid, start, goal, policy, p => admissibleHeuristic(grid, p, goal), false, false);
  if (algorithm === 'astar') return bestFirst(grid, start, goal, policy, p => admissibleHeuristic(grid, p, goal), true, true);
  throw new Error(`Unknown search algorithm: ${algorithm}`);
}
