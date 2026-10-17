import test from 'node:test';
import assert from 'node:assert/strict';
import { runSimulation } from '../src/modules/os-labs/kernel/index.js';
import { createSchedulingModel } from '../src/modules/os-labs/scheduling.js';
import { createProcessModel } from '../src/modules/os-labs/processModel.js';
import { replacePages, beladyDemonstration } from '../src/modules/os-labs/virtualMemory.js';
import { scheduleDisk } from '../src/modules/os-labs/diskScheduling.js';
import { translatePagedAddress, segmentAddress, effectiveAccessTime, allocateContiguous } from '../src/modules/os-labs/memory.js';
import { detectWaitForCycles, detectMultiInstanceDeadlock } from '../src/modules/os-labs/deadlock.js';
import { lostUpdateDemo, runPeterson, semaphore, producerConsumer, readersWriters, diningPhilosophers, priorityInversion } from '../src/modules/os-labs/synchronisation.js';
import { mailbox, pipeSimulation } from '../src/modules/os-labs/ipc.js';

test('kernel is deterministic for scheduling and process models and snapshots rewind state', () => {
  const input = { model: createSchedulingModel(), workload: [{ pid: 'P1', arrival: 0, burst: 2 }, { pid: 'P2', arrival: 1, burst: 1 }], params: { algorithm: 'RR', quantum: 1 }, seed: 42 };
  const one = runSimulation(input), two = runSimulation(input);
  assert.deepEqual(one.events, two.events);
  assert.deepEqual(one.snapshots, two.snapshots);
  assert.deepEqual(runSimulation({ model: createProcessModel(), workload: [{ pid: 'P1', bursts: [1, 2] }], seed: 42 }).events,
    runSimulation({ model: createProcessModel(), workload: [{ pid: 'P1', bursts: [1, 2] }], seed: 42 }).events);
  assert.ok(one.snapshots.length > 1);
  assert.equal(runSimulation({ ...input, maxSteps: 1 }).status, 'STEP_LIMIT');
});

test('RR queues a boundary arrival before the expired process and accounts for idle time', () => {
  const result = runSimulation({ model: createSchedulingModel(), workload: [{ pid: 'P1', arrival: 0, burst: 3 }, { pid: 'P2', arrival: 1, burst: 1 }], params: { algorithm: 'RR', quantum: 1 } });
  assert.deepEqual(result.metrics.timeline.slice(0, 3).map(slot => slot.pid), ['P1', 'P2', 'P1']);
  const idle = runSimulation({ model: createSchedulingModel(), workload: [{ pid: 'P1', arrival: 3, burst: 1 }] });
  assert.equal(idle.metrics.timeline[0].kind, 'IDLE');
});

test('SJF is optimal over same-time fixed jobs and scheduling reports distinct waiting/response metrics', () => {
  const jobs = [{ pid: 'P1', arrival: 0, burst: 6 }, { pid: 'P2', arrival: 0, burst: 2 }, { pid: 'P3', arrival: 0, burst: 4 }];
  const run = policy => runSimulation({ model: createSchedulingModel(), workload: jobs, params: { algorithm: policy } }).metrics;
  assert.ok(run('SJF').averageWaiting <= run('FCFS').averageWaiting);
  const staggered = runSimulation({ model: createSchedulingModel(), workload: [{ pid: 'P1', arrival: 0, burst: 3 }, { pid: 'P2', arrival: 0, burst: 3 }], params: { algorithm: 'RR', quantum: 1 } }).metrics.perTask;
  assert.ok(staggered.some(row => row.waiting !== row.response));
});

test('SRTF, priority, EDF, RR context switches, and Rate Monotonic metrics respect their rules', () => {
  const staggered=[{pid:'P1',arrival:0,burst:8,priority:4,deadline:20,period:12},{pid:'P2',arrival:1,burst:4,priority:2,deadline:7,period:8},{pid:'P3',arrival:2,burst:2,priority:1,deadline:3,period:6}];
  const metrics=algorithm=>runSimulation({model:createSchedulingModel(),workload:staggered,params:{algorithm,quantum:1}}).metrics;
  assert.ok(metrics('SRTF').averageWaiting<=metrics('SJF').averageWaiting);
  assert.equal(metrics('EDF').missedDeadlines.length>0,true);
  const prioritized=runSimulation({model:createSchedulingModel(),workload:[{pid:'P1',arrival:0,burst:1,priority:5},{pid:'P2',arrival:0,burst:1,priority:1}],params:{algorithm:'PRIORITY'}}).metrics;
  assert.equal(prioritized.timeline[0].pid,'P2');
  const switched=runSimulation({model:createSchedulingModel(),workload:[{pid:'P1',arrival:0,burst:1},{pid:'P2',arrival:0,burst:1}],params:{algorithm:'FCFS',contextSwitchCost:2}}).metrics;
  assert.equal(switched.timeline[1].kind,'SWITCH'); assert.equal(switched.cpuUtilisation,0.5); assert.equal(switched.contextSwitches,1);
  const rm=runSimulation({model:createSchedulingModel(),workload:[{pid:'R1',arrival:0,burst:1,period:4},{pid:'R2',arrival:0,burst:1,period:4}],params:{algorithm:'RM'}}).metrics;
  assert.equal(rm.rateMonotonic.utilization,0.5); assert.ok(rm.rateMonotonic.passesSufficientBound); assert.equal(rm.perTask.length,6);
  const mlfq=runSimulation({model:createSchedulingModel(),workload:[{pid:'P1',arrival:0,burst:7}],params:{algorithm:'MLFQ'}});
  assert.ok(mlfq.events.some(event=>event.type==='QUEUE_DEMOTION'));
  const aged=runSimulation({model:createSchedulingModel(),workload:[{pid:'P1',arrival:0,burst:5,priority:1},{pid:'P2',arrival:0,burst:1,priority:9}],params:{algorithm:'PRIORITY_AGING',agingInterval:1}}).metrics;
  assert.ok(aged.perTask.find(task=>task.pid==='P2').start!==null);
});

test('process model executes CPU–I/O cycles and keeps caused state transitions', () => {
  const run=runSimulation({model:createProcessModel(),workload:[{pid:'P1',name:'Incident',bursts:[1,2],resources:['radio']}],maxSteps:10});
  assert.equal(run.status,'COMPLETED');
  assert.ok(run.events.some(event=>event.detail==='RUNNING → WAITING'&&event.reason.includes('I/O')));
  assert.ok(run.events.every(event=>event.reason.length>0));
  assert.equal(run.finalState.processes[0].state,'TERMINATED');
});

test('Banker safe sequence retains a Work trace and refused requests do not mutate matrices', async () => {
  const { bankerSafeSequence, evaluateBankerRequest } = await import('../src/osAlgorithms.js');
  const a = [[0,1,0],[2,0,0],[3,0,2],[2,1,1],[0,0,2]], m = [[7,5,3],[3,2,2],[9,0,2],[2,2,2],[4,3,3]], v = [3,3,2];
  const result = bankerSafeSequence(v, a, m);
  assert.equal(result.safe, true); assert.equal(result.workTrace.length, result.order.length + 1);
  const initialRequest = evaluateBankerRequest(v, a, m, 0, [0,2,0]);
  assert.equal(initialRequest.granted, true); assert.deepEqual(v, [3,3,2]);
  const first=evaluateBankerRequest(v,a,m,1,[1,0,2]); assert.equal(first.granted,true);
  const availableBefore=[...first.available], allocationBefore=first.allocation.map(row=>[...row]);
  const corrected=evaluateBankerRequest(first.available,first.allocation,m,0,[0,2,0]);
  assert.equal(corrected.granted,false); assert.deepEqual(first.available,availableBefore); assert.deepEqual(first.allocation,allocationBefore);
});

test('page replacement computes Belady 9/10 and Optimal is no worse on a fixture', () => {
  const result = beladyDemonstration();
  assert.equal(result.threeFrames.faults, 9); assert.equal(result.fourFrames.faults, 10);
  const refs = [7,0,1,2,0,3,0,4,2,3,0,3,2];
  assert.ok(replacePages(refs, 3, 'OPTIMAL').faults <= replacePages(refs, 3, 'LRU').faults);
  assert.ok(replacePages(refs, 3, 'OPTIMAL').faults <= replacePages(refs, 3, 'FIFO').faults);
});

test('100 seeded page traces preserve Optimal lower-bound and LRU stack invariants', async () => {
  const { mulberry32 } = await import('../src/modules/os-labs/kernel/index.js');
  for(let seed=1;seed<=100;seed+=1){const rng=mulberry32(seed),refs=Array.from({length:30},()=>Math.floor(rng()*8)),frames=1+seed%5;
    const optimal=replacePages(refs,frames,'OPTIMAL').faults,lru=replacePages(refs,frames,'LRU').faults,fifo=replacePages(refs,frames,'FIFO').faults;
    assert.ok(optimal<=lru&&optimal<=fifo,`Optimal lower-bound failed at seed ${seed}`);
    assert.ok(replacePages(refs,frames+1,'LRU').faults<=lru,`LRU stack invariant failed at seed ${seed}`);
  }
});

test('memory helpers validate hand-computed addresses, traps, and external fragmentation', () => {
  assert.deepEqual(translatePagedAddress(14, 4, [3,7,2,5]), { valid: true, page: 3, offset: 2, frame: 5, physicalAddress: 22, arithmetic: '5 × 4 + 2 = 22' });
  assert.equal(segmentAddress([{ base: 100, limit: 8 }], 0, 8).valid, false);
  assert.equal(effectiveAccessTime(0.5, 100, 10), 160);
  assert.ok(allocateContiguous([100, 500, 200], [{ id: 'A', size: 180 }], 'BEST_FIT').largestHole === 500);
});

test('disk policies return movement path and disk endpoint behavior', () => {
  const requests = [98, 183, 37, 122, 14, 124, 65, 67];
  assert.ok(scheduleDisk(requests, 53, 'SSTF').totalMovement <= scheduleDisk(requests, 53, 'FCFS').totalMovement);
  assert.ok(scheduleDisk(requests, 53, 'SCAN', 'right').path.includes(199));
  assert.equal(scheduleDisk(requests, 53, 'C-LOOK', 'right').path.includes(199), false);
});

test('synchronization and IPC expose lost updates, nonnegative semaphores, and blocking', () => {
  const race = lostUpdateDemo(7); assert.equal(race.unsynchronized.lostUpdate, true); assert.equal(race.mutex.correct, true);
  assert.equal(semaphore(0, [{ type: 'wait', actor: 'A' }]).count, 0);
  assert.equal(producerConsumer(1, [{ type: 'produce', value: 'r1' }, { type: 'produce', value: 'r2' }]).trace[1].state, 'WAITING_FULL');
  const box = mailbox(1); box.send('a'); assert.equal(box.send('b').blocked, true); assert.equal(box.receive().message, 'a');
  assert.deepEqual(lostUpdateDemo(7).unsynchronized.operations,lostUpdateDemo(7).unsynchronized.operations);
  const peterson=runPeterson(); assert.equal(peterson.mutualExclusion,true);assert.equal(peterson.progress,true);assert.equal(peterson.boundedWaiting,true);
  const buffer=producerConsumer(1,[{type:'produce',value:'a'},{type:'produce',value:'b'},{type:'consume'},{type:'consume'},{type:'consume'}]);
  assert.ok(buffer.trace.some(item=>item.state==='WAITING_FULL'));assert.ok(buffer.trace.some(item=>item.state==='WAITING_EMPTY'));
  assert.equal(readersWriters(12,'reader-preference').writerBlockedThroughHorizon,true);
  assert.equal(readersWriters(12,'fair').writerBlockedThroughHorizon,false);
  assert.equal(diningPhilosophers('none').deadlocked,true);
  for(const fix of ['asymmetric','waiter','tryLock'])assert.equal(diningPhilosophers(fix).deadlocked,false);
  assert.equal(priorityInversion(true).bounded,true);assert.equal(priorityInversion(false).bounded,false);
  const pipe=pipeSimulation(['a','b','c'],2);assert.ok(pipe.trace.some(item=>item.type==='PRODUCER_WAITING'));assert.ok(pipe.trace.some(item=>item.type==='CONSUMER_WAITING'));
});

test('deadlock detectors name wait-for cycle members and blocked processes', () => {
  assert.deepEqual(detectWaitForCycles([['P0','P1'],['P1','P0']]), [['P0','P1','P0']]);
  assert.deepEqual(detectMultiInstanceDeadlock([0], [[1],[1]], [[1],[1]]).deadlocked, ['P0','P1']);
});

test('worker task definitions return deterministic, structured-cloneable module results', async () => {
  const { runLabTask }=await import('../src/modules/os-labs/runLabTask.js');
  const one=runLabTask('deadlock',{conditions:{mutualExclusion:true,holdAndWait:true,noPreemption:true,circularWait:true}});
  const two=runLabTask('deadlock',{conditions:{mutualExclusion:true,holdAndWait:true,noPreemption:true,circularWait:true}});
  assert.deepEqual(one,two);assert.equal(one.cycles.length,1);
  const prevented=runLabTask('deadlock',{conditions:{mutualExclusion:true,holdAndWait:true,noPreemption:true,circularWait:false}});
  assert.equal(prevented.cycles.length,0);assert.equal(prevented.detection.deadlocked.length,0);
  assert.doesNotThrow(()=>structuredClone(runLabTask('sync',{seed:7})));
});
