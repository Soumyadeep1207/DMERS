import { runSimulation } from '../src/modules/os-labs/kernel/index.js';
import { createSchedulingModel } from '../src/modules/os-labs/scheduling.js';

const workload = [
  { pid: 'P1', arrival: 0, burst: 6, priority: 2, deadline: 14, period: 16 },
  { pid: 'P2', arrival: 1, burst: 2, priority: 1, deadline: 8, period: 10 },
  { pid: 'P3', arrival: 2, burst: 4, priority: 3, deadline: 12, period: 14 },
  { pid: 'P4', arrival: 4, burst: 3, priority: 2, deadline: 16, period: 18 },
];
const names = ['FCFS','SJF','SRTF','PRIORITY','PRIORITY_AGING','RR','MLFQ','EDF','RM'];
console.log('DMERS OS scheduler comparison · same synthetic workload · seed 303');
console.log('Algorithm        AvgWT  AvgRT  Util   Ticks');
for (const algorithm of names) {
  const result = runSimulation({ model:createSchedulingModel(), workload,
    params:{ algorithm, quantum:2, agingInterval:3 }, seed:303, maxSteps:5000 });
  const metrics=result.metrics;
  console.log(`${algorithm.padEnd(16)} ${metrics.averageWaiting.toFixed(2).padStart(5)}  ${metrics.averageResponse.toFixed(2).padStart(5)}  ${(metrics.cpuUtilisation*100).toFixed(1).padStart(5)}% ${String(result.steps).padStart(6)}`);
}
