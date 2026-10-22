import { incidentAdvisory, rankTeams, matchHospitals } from '../src/modules/ai/triage.js';
import { clock, asOf } from './fixtures.js';

const incident = { id: 'DEMO-1', severity: 'HIGH', status: 'RESPONDING', asOf };
const teams = [
  { id: 'T-1', name: 'Flood Rescue', capabilities: ['flood'], availability: 1, assigned: 0, capacity: 2, asOf },
  { id: 'T-2', name: 'Medical Team', capabilities: ['medical'], availability: 0.6, assigned: 1, capacity: 3, asOf },
];
const hospitals = [
  { id: 'H-1', name: 'Vellore Receiving', beds_available: 4, receivingStatus: 'ACCEPTING', asOf },
  { id: 'H-2', name: 'Full Hospital', beds_available: 0, receivingStatus: 'ACCEPTING', asOf },
];
const routeCost = hospital => (hospital.id === 'H-1' ? 3 : 1);

console.log('ai-triage: single incident demonstration\n');
const incidentResult = incidentAdvisory(incident, { clock });
console.log(`Incident score: ${incidentResult.score.toFixed(2)}`);
for (const row of incidentResult.evidence) console.log(`  ${row.factor}: ${row.value} (contribution ${row.contribution})`);

console.log('\nRanked teams (requirement: medical):');
for (const item of rankTeams(teams, 'medical', { clock })) {
  console.log(`  ${item.subject}: score ${item.score.toFixed(2)}`);
  for (const row of item.evidence) console.log(`    ${row.factor} = ${row.value} x ${row.weight} = ${row.contribution.toFixed(2)}`);
}

console.log('\nQualifying hospitals (eligibility filter, ordered by route cost):');
for (const item of matchHospitals(hospitals, routeCost, { now: Date.parse(asOf), clock })) {
  const beds = item.evidence.find(row => row.factor === 'Recorded free beds');
  console.log(`  ${item.subject}: ${beds.value} beds, as of ${beds.asOf}`);
}

console.log(`\nLimitations: ${incidentResult.limitations.join(' | ')}`);
console.log(`Human review required: ${incidentResult.requiresHumanAction}`);
