import { runSimulation } from '../src/modules/os-labs/kernel/index.js';
import { bankerSafeSequence, evaluateBankerRequest } from '../src/osAlgorithms.js';
import { detectWaitForCycles, breakCoffmanConditions, detectMultiInstanceDeadlock } from '../src/modules/os-labs/deadlock.js';
const allocation=[[0,1,0],[2,0,0],[3,0,2],[2,1,1],[0,0,2]], maximum=[[7,5,3],[3,2,2],[9,0,2],[2,2,2],[4,3,3]], available=[3,3,2];
console.log('DMERS deadlock lab');
console.log(`Banker baseline safe: ${bankerSafeSequence(available,allocation,maximum).safe}`);
const p1=evaluateBankerRequest(available,allocation,maximum,1,[1,0,2]);
const p0=p1.granted?evaluateBankerRequest(p1.available,p1.allocation,maximum,0,[0,2,0]):p1;
console.log(`P1 [1,0,2]: ${p1.granted?'granted':'refused'}; then P0 [0,2,0]: ${p0.granted?'granted':'refused'}`);
console.log(`Wait-for cycle: ${detectWaitForCycles([['P0','P1'],['P1','P2'],['P2','P0']]).map(cycle=>cycle.join(' -> ')).join('; ')}`);
console.log(`Multi-instance blocked processes: ${detectMultiInstanceDeadlock([0,0],[[1,0],[0,1],[1,0]],[[0,1],[1,0],[0,1]]).deadlocked.join(', ')}`);
for(const condition of ['mutualExclusion','holdAndWait','noPreemption','circularWait']){
  const toggles=Object.fromEntries(['mutualExclusion','holdAndWait','noPreemption','circularWait'].map(name=>[name,name!==condition]));
  const state=breakCoffmanConditions(toggles); console.log(`Break ${condition}: prevention demonstrated (${state.filter(item=>!item.holds).map(item=>item.label).join(', ')})`);
}
