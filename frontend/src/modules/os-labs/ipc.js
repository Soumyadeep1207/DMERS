export function mailbox(capacity = 2) {
  const queue = [], blockedSenders = [], blockedReceivers = [], events = [];
  return {
    queue, blockedSenders, blockedReceivers, events,
    send(message, { blocking = true } = {}) {
      if (blockedReceivers.length) { blockedReceivers.shift(); events.push({ type: 'DIRECT_HANDOFF', message, reason: 'Sender delivered directly to a blocked receiver.' }); return { sent: true, blocked: false, handedOff: true }; }
      if (queue.length >= capacity) { if (blocking) blockedSenders.push(message); events.push({ type: 'SEND_BLOCKED', message, reason: 'Mailbox is full; sender waits for a receiver.' }); return { sent: false, blocked: blocking }; }
      queue.push(message); events.push({ type: 'SEND', message, reason: 'Message copied into the bounded mailbox.' }); return { sent: true, blocked: false };
    },
    receive({ blocking = true } = {}) {
      if (!queue.length && blockedSenders.length) { const message=blockedSenders.shift(); events.push({ type: 'DIRECT_HANDOFF', message, reason: 'Blocked sender handed its message directly to the waiting receiver.' }); return { received:true,message,blocked:false,handedOff:true }; }
      if (!queue.length) { if (blocking) blockedReceivers.push(true); events.push({ type: 'RECEIVE_BLOCKED', reason: 'Mailbox is empty; receiver waits for a sender.' }); return { received: false, blocked: blocking }; }
      const message = queue.shift();
      if (blockedSenders.length && queue.length < capacity) queue.push(blockedSenders.shift());
      events.push({ type: 'RECEIVE', message, reason: 'Receiver removed the oldest queued message.' }); return { received: true, message, blocked: false };
    },
  };
}

export function compareIpc(messageCount = 4, bytesPerMessage = 64) {
  return { sharedMemory: { messages: messageCount, bytesCopied: 0, synchronizationRequired: true, blockingTicks: 0 },
    messagePassing: { messages: messageCount, bytesCopied: messageCount * bytesPerMessage, synchronizationRequired: 'kernel mailbox', blockingTicks: 0 },
    assumptions: 'Counts are from this configured workload; they are not universal performance measurements.' };
}

export function pipeSimulation(values, capacity = 2) {
  const pipe = [], trace = [], received = [], waitingWriters = [], waitingReaders = [];
  const actions=Array.isArray(values)&&values.every(item=>item&&typeof item==='object')?values:[...values.map(value=>({type:'write',value})),...values.map(()=>({type:'read'})),{type:'read'}];
  for (const action of actions) {
    if(action.type==='write'){
      if(waitingReaders.length){waitingReaders.shift();received.push(action.value);trace.push({type:'DIRECT_HANDOFF',value:action.value,pipe:[...pipe],reason:'Writer delivered bytes to a blocked reader.'});}
      else if(pipe.length>=capacity){waitingWriters.push(action.value);trace.push({type:'PRODUCER_WAITING',value:action.value,pipe:[...pipe],reason:'Pipe buffer full; producer blocks until a read frees space.'});}
      else{pipe.push(action.value);trace.push({type:'WRITE',value:action.value,pipe:[...pipe],reason:'Producer wrote bytes to the pipe.'});}
    }else if(action.type==='read'){
      if(!pipe.length&&waitingWriters.length){const value=waitingWriters.shift();received.push(value);trace.push({type:'DIRECT_HANDOFF',value,pipe:[...pipe],reason:'Blocked writer handed bytes directly to the waiting reader.'});}
      else if(!pipe.length){waitingReaders.push(true);trace.push({type:'CONSUMER_WAITING',pipe:[...pipe],reason:'Pipe buffer empty; consumer blocks until a write arrives.'});}
      else{const value=pipe.shift();received.push(value);trace.push({type:'READ',value,pipe:[...pipe],reason:'Consumer read the oldest bytes.'});if(waitingWriters.length){const next=waitingWriters.shift();pipe.push(next);trace.push({type:'WRITER_WAKE',value:next,pipe:[...pipe],reason:'The read freed space; the oldest blocked writer resumed.'});}}
    }
  }
  return { trace, received, remaining: pipe, waitingWriters, waitingReaders };
}

export function signalInterruption(task, signal = 'EMERGENCY') {
  const saved = { programCounter: task.programCounter ?? 0, registers: { ...(task.registers || {}) } };
  return { events: [
    { type: 'INTERRUPT', reason: `${signal} arrived; the running task context was saved.` },
    { type: 'HANDLER', reason: `${signal} handler runs before the interrupted task resumes.` },
    { type: 'RESUME', reason: `Task resumes at saved program counter ${saved.programCounter}.` },
  ], savedContext: saved, resumedAt: saved.programCounter };
}
