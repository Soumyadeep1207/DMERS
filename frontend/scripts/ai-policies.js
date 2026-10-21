import { ROUTE_POLICIES, cellCost } from '../src/modules/ai/policies.js';
import { search } from '../src/modules/ai/search.js';
import { demoGrid, ORIGIN, TARGET } from './fixtures.js';

const grid = demoGrid();
console.log('ai-policies: same origin/target under fastest, balanced, safer\n');
for (const [policy, weights] of Object.entries(ROUTE_POLICIES)) {
  const result = search(grid, ORIGIN, TARGET, 'astar', policy);
  console.log(`Policy: ${policy} (distance x${weights.w_distance}, risk x${weights.w_risk})`);
  console.log(`  Status: ${result.status}`);
  if (result.status === 'FOUND') {
    console.log(`  Cost: ${result.cost.toFixed(2)} grid units (not travel time)`);
    console.log(`  Distance: ${result.distanceUnits} units`);
    console.log(`  Risk: ${result.riskScore.toFixed(2)}`);
    const [laneRow] = result.path.find(([, c]) => c === 6) ?? [];
    if (laneRow !== undefined) console.log(`  Lane crossed the wall at row ${laneRow} (gap cost ${cellCost(grid[laneRow][6], policy).toFixed(2)})`);
  }
  console.log('');
}
