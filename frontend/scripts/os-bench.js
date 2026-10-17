import { performance } from 'node:perf_hooks';
import { runSimulation } from '../src/modules/os-labs/kernel/index.js';
import { createSchedulingModel } from '../src/modules/os-labs/scheduling.js';
import { createProcessModel } from '../src/modules/os-labs/processModel.js';

const cases=[
  ['scheduling 5,000 ticks',createSchedulingModel(),Array.from({length:10},(_,i)=>({pid:`P${i+1}`,arrival:i,burst:500,priority:i%5,deadline:6000,period:6000})),{algorithm:'RR',quantum:2}],
  ['process 5,000 instructions',createProcessModel(),[{pid:'P1',bursts:[5000]}],{}],
];
console.log('DMERS OS worker-model benchmark · host CPU dependent');
for(const [name,model,workload,params] of cases){
  const started=performance.now(); const result=runSimulation({model,workload,params,seed:303,maxSteps:10000}); const elapsed=performance.now()-started;
  console.log(`${name.padEnd(31)} ${elapsed.toFixed(2).padStart(8)} ms · ${result.steps} steps · ${result.status}${elapsed<150?' · within 150 ms':' · exceeds 150 ms'}`);
}
