import { lostUpdateDemo, runPeterson, semaphore, producerConsumer, readersWriters, diningPhilosophers, priorityInversion } from './synchronisation.js';
import { detectWaitForCycles, detectMultiInstanceDeadlock, breakCoffmanConditions, recoverByTermination } from './deadlock.js';
import { mailbox, compareIpc, pipeSimulation, signalInterruption } from './ipc.js';
import { allocateContiguous, compactMemory, translatePagedAddress, internalFragmentation, segmentAddress, effectiveAccessTime } from './memory.js';
import { replacePages, beladyDemonstration, thrashingCurve } from './virtualMemory.js';
import { scheduleDisk } from './diskScheduling.js';
import { allocateFiles } from './fileSystem.js';
import { analyseHospital } from './hospitalBeds.js';

export function runLabTask(kind, input = {}) {
  switch (kind) {
    case 'sync': {
      const race = lostUpdateDemo(input.seed, input.ambulances, input.dispatchers);
      const box = mailbox(Number(input.capacity) || 2); box.send('Water update'); box.send('Blocked report'); const overflow = box.send('Third message'); const read = box.receive();
      return { race, peterson: runPeterson(), semaphore: semaphore(1, [{ type: 'wait', actor: 'Team A' }, { type: 'wait', actor: 'Team B' }, { type: 'signal', actor: 'Team A' }]),
        producerConsumer: producerConsumer(1, [{ type: 'produce', value: 'R1' }, { type: 'produce', value: 'R2' }, { type: 'consume' }, { type: 'consume' }, { type: 'consume' }]),
        readersWriters: readersWriters(4, input.readerPolicy), philosophers: diningPhilosophers(input.philosopherFix), inversion: priorityInversion(Boolean(input.inheritance)), mailbox: { overflow, read, queue: [...box.queue], events: box.events } };
    }
    case 'deadlock': { const brokenCondition=input.conditions?Object.entries(input.conditions).find(([,value])=>value===false)?.[0]:null;
      const edges=!brokenCondition?[['P0','P1'],['P1','P2'],['P2','P0']]:brokenCondition==='circularWait'?[['P0','P1'],['P1','P2']]:[];
      const cycles=detectWaitForCycles(edges); return { edges, cycles, detection: cycles.length?detectMultiInstanceDeadlock([0,0], [[1,0],[0,1],[1,0]], [[0,1],[1,0],[0,1]]):{deadlocked:[],reason:`The selected prevention control breaks ${brokenCondition||'a necessary condition'} in this teaching graph.`},
      conditions: breakCoffmanConditions(input.conditions), recovery: recoverByTermination([{ pid: 'P0', priority: 2, allocation: [1,0] }, { pid: 'P1', priority: 7, allocation: [0,1] }], [0,0]), resolvedByPrevention: Boolean(brokenCondition) }; }
    case 'ipc': { const box = mailbox(Number(input.capacity) || 2); const a = box.send('Verified flood report'), b = box.send('Hospital beds update'), c = box.send('Road closure'); const one = box.receive(); const pipe = pipeSimulation(['incident:1','incident:2','incident:3'], Number(input.capacity) || 2); return { mailbox: { a, b, c, one, queue: [...box.queue], events: box.events }, sharedVsMessage: compareIpc(Number(input.count) || 4, Number(input.bytes) || 64), pipe, signal: signalInterruption({ programCounter: 12, registers: { r1: 4, r2: 9 } }) }; }
    case 'memory': { const allocation = allocateContiguous([100, 500, 200, 300], [{ id: 'Triage cache', size: 120 }, { id: 'Map tiles', size: 210 }, { id: 'Incident archive', size: 90 }], input.allocation || 'BEST_FIT'); return { allocation, compaction: compactMemory(allocation.holes), paging: translatePagedAddress(Number(input.address) || 14, 4, [3,7,2,5]), fragmentation: internalFragmentation(14,4), segmentationValid: segmentAddress([{ base: 1000, limit: 100 }], 0, 24), segmentationTrap: segmentAddress([{ base: 1000, limit: 100 }], 0, 100), tlb: effectiveAccessTime(0.8, 100, 10) }; }
    case 'virtual': { const references = String(input.references || '1,2,3,4,1,2,5,1,2,3,4,5').split(',').map(Number).filter(Number.isFinite); const frames = Number(input.frames) || 3; return { results: ['FIFO','LRU','OPTIMAL','CLOCK','LFU'].map(algorithm => replacePages(references, frames, algorithm)), belady: beladyDemonstration(), thrashing: thrashingCurve(references, Math.max(1, Number(input.maxFrames) || 8), 'LRU'), references }; }
    case 'disk': { const requests = String(input.requests || '98,183,37,122,14,124,65,67').split(',').map(Number).filter(Number.isFinite); return { results: ['FCFS','SSTF','SCAN','C-SCAN','LOOK','C-LOOK'].map(algorithm => scheduleDisk(requests, Number(input.head ?? 53), algorithm, input.direction || 'right')), files: ['CONTIGUOUS','LINKED','INDEXED'].map(scheme => allocateFiles([{ name: 'incident-archive', blocks: 5 }, { name: 'offline-map-cache', blocks: 7 }], 24, scheme)) }; }
    case 'beds': return analyseHospital(input);
    default: throw new RangeError(`Unknown OS laboratory module: ${kind}`);
  }
}
