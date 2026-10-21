import { search } from '../src/modules/ai/search.js';
import { applyScenario } from '../src/modules/ai/scenario.js';
import { demoGrid, ORIGIN, TARGET } from './fixtures.js';

const seed = 42;
const grid = demoGrid();
const before = search(grid, ORIGIN, TARGET, 'astar', 'balanced');

const epicentre = [6, 6];
const flooded = applyScenario(grid, { type: 'flood', epicentre, seed });
const after = search(flooded, ORIGIN, TARGET, 'astar', 'balanced');

console.log('ai-scenario: route before and after a seeded flood\n');
console.log(`Seed: ${seed}`);
console.log(`Scenario inputs: { type: "flood", epicentre: [${epicentre}] }`);
console.log(`Original route: status ${before.status}, cost ${before.cost?.toFixed(2) ?? '-'}, risk ${before.riskScore?.toFixed(2) ?? '-'}`);
console.log(`Scenario route: status ${after.status}, cost ${after.cost?.toFixed(2) ?? '-'}, risk ${after.riskScore?.toFixed(2) ?? '-'}`);
console.log(`Unreachable after scenario: ${after.status === 'UNREACHABLE'}`);
console.log('Limitations: route costs are grid units, not travel time; a scenario can only worsen cells.');
