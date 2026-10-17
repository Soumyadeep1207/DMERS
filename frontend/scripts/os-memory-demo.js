import { allocateContiguous, translatePagedAddress } from '../src/modules/os-labs/memory.js';
import { beladyDemonstration } from '../src/modules/os-labs/virtualMemory.js';
console.log('DMERS memory & virtual-memory lab');
for(const strategy of ['FIRST_FIT','BEST_FIT','WORST_FIT']){
  const result=allocateContiguous([100,500,200,300],[{id:'A',size:120},{id:'B',size:210},{id:'C',size:90}],strategy);
  console.log(`${strategy.padEnd(10)} placements ${result.placements.map(item=>`${item.request}@${item.start}`).join(', ')}; largest hole ${result.largestHole}`);
}
const address=translatePagedAddress(14,4,[3,7,2,5]);
console.log(`Address 14: page ${address.page}, offset ${address.offset}, frame ${address.frame}, physical ${address.physicalAddress}`);
const belady=beladyDemonstration();
console.log(`FIFO Belady: 3 frames ${belady.threeFrames.faults} faults; 4 frames ${belady.fourFrames.faults} faults`);
console.log('Reference : 1 2 3 4 1 2 5 1 2 3 4 5');
for(const key of ['threeFrames','fourFrames']) console.log(`${key.padEnd(11)}: ${belady[key].trace.map(row=>row.frames.join('')).join(' | ')}`);
