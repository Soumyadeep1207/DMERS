import { search } from '../src/modules/ai/search.js';
import { demoGrid, ORIGIN, TARGET } from './fixtures.js';

const grid = demoGrid();
const algorithms = ['bfs', 'dfs', 'ucs', 'greedy', 'astar'];
console.log('ai-search: all five algorithms on the same fixture (policy: balanced)\n');
const rows = algorithms.map(algorithm => ({ algorithm, ...search(grid, ORIGIN, TARGET, algorithm, 'balanced') }));
const header = ['Algorithm', 'Status', 'Cost', 'Distance', 'Risk', 'Nodes', 'Optimal'];
console.log(header.join(' | '));
for (const row of rows) {
  console.log([
    row.algorithm.toUpperCase(), row.status,
    row.cost?.toFixed(2) ?? '-', row.distanceUnits ?? '-', row.riskScore?.toFixed(2) ?? '-',
    row.nodesExplored, row.optimal ? 'yes' : 'no',
  ].join(' | '));
}
const ucs = rows.find(r => r.algorithm === 'ucs'), astar = rows.find(r => r.algorithm === 'astar');
console.log(`\nUCS/A* cost agreement: ${ucs.cost === astar.cost}`);
console.log(`A* nodes <= UCS nodes: ${astar.nodesExplored <= ucs.nodesExplored} (${astar.nodesExplored} vs ${ucs.nodesExplored})`);
