import { choosePolicy, HIGH_HAZARD } from '../src/modules/ai/policies.js';
import { clock, asOf } from './fixtures.js';

const fixtures = [
  { name: 'R1 - high hazard', input: { hazardLevel: 0.85, availableUnits: 3, targetCount: 2, severity: 'HIGH' } },
  { name: 'R2 - unit scarcity', input: { hazardLevel: 0.1, availableUnits: 1, targetCount: 3, severity: 'HIGH' } },
  { name: 'R3 - critical severity', input: { hazardLevel: 0.1, availableUnits: 3, targetCount: 1, severity: 'CRITICAL' } },
  { name: 'R4 - default', input: { hazardLevel: 0.1, availableUnits: 3, targetCount: 1, severity: 'MODERATE' } },
];

console.log(`ai-auto: four fixtures, one per rule (high-hazard threshold ${HIGH_HAZARD})\n`);
for (const fixture of fixtures) {
  const advisory = choosePolicy({ ...fixture.input, asOf, clock });
  const [ruleRow, explanationRow] = advisory.evidence;
  console.log(`Fixture: ${fixture.name}`);
  console.log(`  Triggering values: ${JSON.stringify(fixture.input)}`);
  console.log(`  Rule: ${ruleRow.source}`);
  console.log(`  Explanation: ${explanationRow.value}`);
  console.log(`  Selected policy: ${advisory.recommendation}`);
  console.log('');
}
