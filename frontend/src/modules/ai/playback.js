import { cellCost } from './policies.js';

/**
 * Replays an already-computed route one cell at a time. The route itself is
 * treated as an immutable input: playback never re-runs search. `createPlayback`
 * reports an invalid route explicitly instead of silently doing nothing.
 */
export function createPlayback(route) {
  if (!route || route.status !== 'FOUND' || !Array.isArray(route.path) || route.path.length === 0) {
    return { route: null, index: 0, status: 'INVALID' };
  }
  return { route, index: 0, status: 'READY' };
}

export function isComplete(state) {
  return state.status !== 'INVALID' && state.index === state.route.path.length - 1;
}

export function currentCell(state) {
  return state.status === 'INVALID' ? null : state.route.path[state.index];
}

export function traversedCells(state) {
  return state.status === 'INVALID' ? [] : state.route.path.slice(0, state.index + 1);
}

export function step(state) {
  if (state.status === 'INVALID' || isComplete(state)) return state;
  return { ...state, index: state.index + 1 };
}

/**
 * Cost accumulated over cells already traversed, computed from the route's
 * own cells and the grid/policy that produced it - bookkeeping on a finished
 * route, never a re-run of pathfinding.
 */
export function accumulatedCost(state, grid, policy) {
  if (state.status === 'INVALID') return null;
  return state.route.path
    .slice(1, state.index + 1)
    .reduce((total, [r, c]) => total + cellCost(grid[r][c], policy), 0);
}
