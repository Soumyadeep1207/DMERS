/** Five-state incident process model with CPU/I-O bursts and forked work. */
export function createProcessModel() {
  return {
    init({ workload }) {
      const processes = workload.map((item, index) => ({ pid: item.pid || `P${index + 1}`, parent: item.parent || null, task: item.task || item.name || 'incident',
        priority: item.priority ?? 5, bursts: [...(item.bursts || [item.burst || 2])].map(value => Math.max(1, Number(value))), burstIndex: 0,
        remaining: Math.max(1, Number((item.bursts || [item.burst || 2])[0])), state: 'NEW', pc: 0, resourcesHeld: [...(item.resources || [])],
        accumulatedCpu: 0, ioWait: 0, contextSwitches: 0, cause: 'created' }));
      return { processes, t: 0, running: null, transitions: [], completed: [] };
    },
    isFinished(s) { return s.processes.every(process => process.state === 'TERMINATED'); },
    snapshot(s) { return { t:s.t, running:s.running, completed:[...s.completed], processes:s.processes.map(process=>({...process,bursts:[...process.bursts],resourcesHeld:[...process.resourcesHeld]})), transitionCount:s.transitions.length }; },
    stallKey(s) { return JSON.stringify(s.processes.map(process=>[process.pid,process.state,process.pc,process.remaining,process.burstIndex,process.ioWait])); },
    step(s) {
      const events = [], move = (process, to, reason) => {
        const from = process.state; process.state = to; process.cause = reason;
        const event = { t: s.t, type: 'STATE', actor: process.pid, detail: `${from} → ${to}`, reason: `${process.pid} moved from ${from} to ${to}: ${reason}.` };
        s.transitions.push(event); events.push(event);
      };
      for (const process of s.processes) if (process.state === 'NEW') move(process, 'READY', 'incident task entered the runnable queue');
      for (const process of s.processes) if (process.state === 'WAITING') {
        process.ioWait += 1; process.burstIndex += 1;
        if (process.burstIndex < process.bursts.length && process.ioWait >= 1) {
          process.remaining = process.bursts[process.burstIndex]; process.ioWait = 0; move(process, 'READY', 'hospital-bed notification or I/O wait completed');
        } else if (process.burstIndex >= process.bursts.length) move(process, 'TERMINATED', 'all CPU/I-O burst cycles are complete');
      }
      if (!s.running) {
        const next = s.processes.filter(item => item.state === 'READY').sort((a, b) => a.priority - b.priority || String(a.pid).localeCompare(String(b.pid)))[0];
        if (next) { s.running = next.pid; next.contextSwitches += 1; move(next, 'RUNNING', 'dispatcher selected the highest-priority ready task'); }
      }
      if (s.running) {
        const process = s.processes.find(item => item.pid === s.running);
        process.pc += 1; process.accumulatedCpu += 1; process.remaining -= 1;
        events.push({ t: s.t, type: 'CPU', actor: process.pid, detail: `PC=${process.pc}`, reason: `${process.pid} executed its next simulated instruction at program counter ${process.pc}.` });
        if (process.remaining <= 0) {
          s.running = null;
          if (process.burstIndex + 1 < process.bursts.length) move(process, 'WAITING', 'CPU burst ended; waiting for the next I/O event');
          else move(process, 'TERMINATED', 'final CPU burst completed');
        }
      }
      s.t += 1;
      return { state: s, events };
    },
    metrics(s) { return { transitions: s.transitions.length, terminated: s.processes.filter(item => item.state === 'TERMINATED').length, processes: s.processes }; },
  };
}

export function forkIncident(parent, childTasks = ['triage', 'transport', 'supply']) {
  return childTasks.map((task, index) => ({ pid: `${parent.pid}.${index + 1}`, parent: parent.pid, task, priority: parent.priority, bursts: [1, 2] }));
}
