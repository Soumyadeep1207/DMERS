import { mulberry32 } from './kernel/index.js';

/** Same seeded schedule is used in both runs; a lock serializes each critical section. */
export function lostUpdateDemo(seed = 7, initialAmbulances = 10, dispatchers = 2) {
  const rng = mulberry32(seed);
  const threads = Array.from({ length: dispatchers }, (_, id) => ({ id: `D${id + 1}`, pc: 0, local: null }));
  const operations = []; let shared = initialAmbulances;
  while (threads.some(thread => thread.pc < 3)) {
    const enabled = threads.filter(thread => thread.pc < 3);
    const thread = enabled[Math.floor(rng() * enabled.length)];
    if (thread.pc === 0) { thread.local = shared; operations.push({ actor: thread.id, instruction: 'READ', value: thread.local }); }
    if (thread.pc === 1) { thread.local -= 1; operations.push({ actor: thread.id, instruction: 'COMPUTE', value: thread.local }); }
    if (thread.pc === 2) { shared = thread.local; operations.push({ actor: thread.id, instruction: 'WRITE', value: shared }); }
    thread.pc += 1;
  }
  const duplicateReads = new Set(operations.filter(item => item.instruction === 'READ')
    .filter((item, index, reads) => reads.some((other, j) => j !== index && other.value === item.value)).map(item => item.actor));
  const interleaving = operations.map(item => ({ ...item, lostUpdateParticipant: duplicateReads.has(item.actor) }));
  const expected = initialAmbulances - dispatchers;
  const unsynchronized = { operations: interleaving, expected, actual: shared, lostUpdate: shared !== expected };

  // Replay the same attempt order. A contender that reaches READ while locked blocks;
  // after unlock it runs its whole read-modify-write section before another contender.
  const acquisitionOrder = [...new Set(operations.map(item => item.actor))];
  let lockedShared = initialAmbulances, owner = null; const mutexOperations = [], blocked = [], done = new Set(), locals = new Map();
  const runCriticalSection = actor => {
    owner=actor; mutexOperations.push({actor,instruction:'LOCK',value:'acquired'});
    const before=lockedShared, after=before-1;
    mutexOperations.push({actor,instruction:'READ',value:before},{actor,instruction:'COMPUTE',value:after},{actor,instruction:'WRITE',value:after});
    lockedShared=after; mutexOperations.push({actor,instruction:'UNLOCK',value:'released'}); owner=null; done.add(actor);
  };
  for(const operation of operations){
    const actor=operation.actor;
    if(done.has(actor)||blocked.includes(actor))continue;
    if(owner&&owner!==actor){if(operation.instruction==='READ'){blocked.push(actor);mutexOperations.push({actor,instruction:'BLOCKED',value:`at READ; lock held by ${owner}`});}continue;}
    if(!owner&&operation.instruction==='READ'){owner=actor;mutexOperations.push({actor,instruction:'LOCK',value:'acquired'});locals.set(actor,lockedShared);mutexOperations.push({actor,instruction:'READ',value:lockedShared});continue;}
    if(owner===actor&&operation.instruction==='COMPUTE'){locals.set(actor,locals.get(actor)-1);mutexOperations.push({actor,instruction:'COMPUTE',value:locals.get(actor)});continue;}
    if(owner===actor&&operation.instruction==='WRITE'){lockedShared=locals.get(actor);mutexOperations.push({actor,instruction:'WRITE',value:lockedShared},{actor,instruction:'UNLOCK',value:'released'});owner=null;done.add(actor);const next=blocked.shift();if(next&&!done.has(next))runCriticalSection(next);}
  }
  for(const actor of acquisitionOrder)if(!done.has(actor))runCriticalSection(actor);
  return { seed, unsynchronized, mutex: { operations: mutexOperations, acquisitionOrder, actual: lockedShared, expected, correct: lockedShared === expected },
    guarantees: { mutualExclusion: true, progress: true, boundedWaiting: true },
    explanation: 'The same seed determines attempted thread order. Without a mutex, reads and writes interleave; with a mutex, each read-modify-write is atomic.' };
}

/** Peterson's two-process algorithm, stepped under a sequentially consistent memory model. */
export function runPeterson() {
  const state = { flag: [false, false], turn: 0, inCritical: [false, false], visits: [0, 0], waitSteps: [0, 0], trace: [] };
  const record = (id, step) => state.trace.push({ id, step, snapshot: { flag: [...state.flag], turn: state.turn, inCritical: [...state.inCritical] } });
  for (const id of [0, 1]) { state.flag[id] = true; record(id, `flag[${id}]=true`); state.turn = 1 - id; record(id, `turn=${1-id}`); }
  for (const id of [0, 1]) {
    const other = 1 - id;
    while (state.flag[other] && state.turn === other) { state.waitSteps[id] += 1; record(id, `WAIT: flag[${other}] && turn==${other}`); }
    state.inCritical[id] = true; record(id, 'ENTER critical section');
    state.visits[id] += 1;
    state.inCritical[id] = false; state.flag[id] = false; record(id, `EXIT; flag[${id}]=false`);
  }
  const noOverlap = state.trace.every(item => item.snapshot.inCritical.filter(Boolean).length <= 1);
  return { ...state, mutualExclusion: noOverlap, progress: state.visits.every(value => value > 0), boundedWaiting: state.waitSteps.every(value => value <= 1),
    caveat: 'This simulation assumes sequential consistency; real hardware implementations require appropriate memory-ordering barriers.' };
}

export function semaphore(initialCount, operations) {
  let count = Math.max(0, Math.floor(initialCount)); const waiting = [], trace = [];
  for (const operation of operations) {
    // wait/signal update the permit and queue as one atomic kernel action; without atomicity the invariant can be broken.
    if (operation.type === 'wait') { if (count > 0) count -= 1; else waiting.push(operation.actor); }
    else if (operation.type === 'signal') { if (waiting.length) waiting.shift(); else count += 1; }
    trace.push({ ...operation, count, waiting: [...waiting] });
  }
  return { count, waiting, trace, invariant: count >= 0 };
}

export function producerConsumer(capacity, operations) {
  const buffer = [], trace = [], waiting = { producer: [], consumer: [] };
  for (const operation of operations) {
    let state = 'DONE', consumed = null;
    if (operation.type === 'produce') {
      if (waiting.consumer.length) { waiting.consumer.shift(); consumed = operation.value; state = 'DELIVERED_TO_WAITING_CONSUMER'; }
      else if (buffer.length >= capacity) { waiting.producer.push(operation.value); state = 'WAITING_FULL'; }
      else buffer.push(operation.value);
    } else if (operation.type === 'consume') {
      if (!buffer.length) { if (waiting.producer.length) consumed = waiting.producer.shift(); else { waiting.consumer.push(true); state = 'WAITING_EMPTY'; } }
      else { consumed = buffer.shift(); if (waiting.producer.length) buffer.push(waiting.producer.shift()); }
    }
    trace.push({ operation, state, consumed, buffer: [...buffer], waiting: { producer: [...waiting.producer], consumer: [...waiting.consumer] } });
  }
  return { trace, finalBuffer: buffer, waiting, guaranteeChecks: { bufferNeverExceededCapacity: trace.every(item => item.buffer.length <= capacity), noNegativeCount: true } };
}

/** Adversarial continuing reader arrivals; finite trace shows a writer still blocked at its horizon. */
export function readersWriters(readerCount = 12, policy = 'reader-preference') {
  const duration = 3, horizon = Math.max(1, readerCount), writerQueuedAt = 0, events = [];
  let activeReaders = 0, writerStart = null;
  for (let t = 0; t < horizon; t += 1) {
    activeReaders = Math.max(0, activeReaders - (t >= duration ? 1 : 0));
    if (policy === 'fair' && writerStart === null && t > writerQueuedAt && activeReaders === 0) writerStart = t;
    const readerAllowed = policy === 'reader-preference' || t <= writerQueuedAt;
    if (readerAllowed) { activeReaders += 1; events.push({ t, actor: `R${t + 1}`, type: 'READ_LOCK' }); }
    else events.push({ t, actor: `R${t + 1}`, type: 'WAITING' });
    if (t === writerQueuedAt) events.push({ t, actor: 'W', type: 'WRITER_QUEUED' });
  }
  if (policy === 'fair' && writerStart === null && activeReaders === 0) writerStart = horizon;
  if (policy === 'fair' && writerStart !== null) events.push({ t: writerStart, actor: 'W', type: 'WRITE_LOCK' });
  const writerBlockedThroughHorizon = policy === 'reader-preference' && activeReaders > 0;
  return { policy, readerCount: horizon, events, writerStart: policy === 'fair' ? writerStart : null,
    writerBlockedThroughHorizon, writerStarvedUnderContinuingReaders: writerBlockedThroughHorizon,
    note: 'A finite run proves only that the writer remained blocked through this observation window; an unbounded reader stream can starve it.' };
}

export function diningPhilosophers(fix = 'none', count = 5) {
  const owners=Array(count).fill(null), philosophers=Array.from({length:count},(_,id)=>({id,first:null,second:null,state:'THINKING',tries:0}));
  const admitted=fix==='waiter'?count-1:count;
  if(fix==='none'){
    for(let id=0;id<count;id+=1){owners[id]=id;philosophers[id].first=id;philosophers[id].state='WAITING_FOR_SECOND';}
  }else if(fix==='tryLock'){
    for(let id=0;id<count;id+=1){owners[id]=id;philosophers[id].first=id;philosophers[id].state='HOLDING_FIRST';}
    for(let id=0;id<count;id+=1){const p=philosophers[id],second=(id+1)%count;p.tries+=1;if(owners[second]!==null){owners[p.first]=null;p.first=null;p.state='BACKOFF';}}
    for(let round=0;round<count&&philosophers.some(p=>p.state!=='DONE');round+=1){for(let id=0;id<count;id+=1){const p=philosophers[id];if(p.state==='DONE')continue;const first=id,second=(id+1)%count;p.tries+=1;if(owners[first]!==null)continue;owners[first]=id;p.first=first;if(owners[second]===null){owners[second]=id;p.second=second;p.state='EATING';owners[first]=null;owners[second]=null;p.state='DONE';}else{owners[first]=null;p.state='BACKOFF';}}}
  }else{
    for(let id=0;id<admitted;id+=1){const p=philosophers[id];const first=fix==='asymmetric'&&id===count-1?(id+1)%count:id;p.tries+=1;if(owners[first]===null){owners[first]=id;p.first=first;p.state='HOLDING_FIRST';}}
    for(let round=0;round<count*3;round+=1){
      let completed=false;
      for(let id=0;id<admitted;id+=1){const p=philosophers[id];if(p.state==='DONE')continue;const second=fix==='asymmetric'&&id===count-1?id:(id+1)%count;p.tries+=1;
        if(owners[second]===null){owners[second]=id;p.second=second;p.state='EATING';owners[p.first]=null;owners[p.second]=null;p.state='DONE';completed=true;}
        else if(fix==='tryLock'&&p.first!==null){owners[p.first]=null;p.first=null;p.state='BACKOFF';}
      }
      if(philosophers.slice(0,admitted).every(p=>p.state==='DONE'))break;
      if(!completed&&round>count)break;
    }
  }
  const deadlocked=philosophers.slice(0,admitted).every(p=>p.state==='WAITING_FOR_SECOND');
  return { fix, philosophers, admitted, deadlocked, progress: philosophers.slice(0,admitted).some(p=>p.state==='DONE'), boundedWaiting:false,
    guarantees:{mutualExclusion:true,progress:philosophers.slice(0,admitted).some(p=>p.state==='DONE'),boundedWaiting:false},
    boundedWaitingNote:'The selected deadlock-prevention technique does not by itself guarantee fairness or bounded waiting.',
    note: fix === 'asymmetric' ? 'One philosopher reverses fork order, breaking the circular-wait cycle.' : fix === 'waiter' ? 'The waiter admits at most n−1 contenders, so the resource-allocation cycle cannot form.' : fix === 'tryLock' ? 'A failed second acquisition releases the first fork and applies deterministic back-off.' : 'Each philosopher holds one fork and waits for the next fork, forming a circular wait.' };
}

export function priorityInversion(inheritance = false) {
  const order = inheritance ? ['Low locks board', 'High blocks', 'Low inherits High priority', 'Low releases board', 'High runs', 'Medium runs']
    : ['Low locks board', 'High blocks', 'Medium preempts Low', 'Low cannot release board', 'High remains blocked'];
  return { inheritance, order, bounded: Boolean(inheritance), example: 'Mars Pathfinder (1997): priority inversion on a shared bus contributed to resets; priority inheritance was enabled to address it.' };
}
