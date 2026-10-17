const byPid = (a, b) => String(a.pid).localeCompare(String(b.pid), undefined, { numeric: true });
const clampInt = (value, fallback = 0) => Number.isFinite(Number(value)) ? Math.max(0, Math.floor(Number(value))) : fallback;

export function createSchedulingModel() {
  return {
    init({ workload, params }) {
      const algorithm = params.algorithm || 'FCFS';
      const periodicTasks = workload.map((task, index) => ({ pid:String(task.pid ?? task.id ?? `P${index+1}`), burst:Math.max(1,clampInt(task.burst,1)), period:clampInt(task.period,Infinity), arrival:clampInt(task.arrival) }));
      let runnable = workload;
      if (algorithm === 'RM') {
        const periods = periodicTasks.filter(task=>Number.isFinite(task.period)&&task.period>0).map(task=>task.period);
        const horizon = clampInt(params.horizon, periods.length ? Math.max(...periods)*3 : 20);
        runnable = workload.flatMap((task,index)=>{
          const base=periodicTasks[index]; if(!Number.isFinite(base.period)||base.period<1)return [task];
          const jobs=[]; for(let release=base.arrival,sequence=0;release<horizon;release+=base.period,sequence+=1) jobs.push({...task,pid:`${base.pid}@${sequence}`,originalPid:base.pid,arrival:release,deadline:release+base.period}); return jobs;
        });
      }
      const tasks = runnable.map((task, index) => ({
        pid: String(task.pid ?? task.id ?? `P${index + 1}`), originalPid: task.originalPid || String(task.pid ?? task.id ?? `P${index+1}`), arrival: clampInt(task.arrival), burst: Math.max(1, clampInt(task.burst, 1)),
        remaining: Math.max(1, clampInt(task.burst, 1)), priority: clampInt(task.priority, 5),
        deadline: clampInt(task.deadline, Infinity), period: clampInt(task.period, Infinity), firstStart: null, completion: null,
        waiting: 0, executed: 0, readySince: null, readyOrder: index, queueLevel: 0, quantumUsed: 0,
      })).sort((a, b) => a.arrival - b.arrival || byPid(a, b));
      return { tasks, t: 0, ready: [], running: null, completed: [], timeline: [], switches: 0, switchRemaining: 0, enqueueCounter: 0,
        previousPid: null, algorithm, quantum: Math.max(1, clampInt(params.quantum, 2)),
        switchCost: clampInt(params.contextSwitchCost), agingInterval: Math.max(1, clampInt(params.agingInterval, 3)), busy: 0, idle: 0, periodicTasks };
    },
    isFinished(s) { return s.completed.length === s.tasks.length; },
    snapshot(s) { return { t: s.t, ready: [...s.ready], running: s.running, completed: [...s.completed], switchRemaining: s.switchRemaining,
      tasks: s.tasks.map(task => ({ ...task })), timelineSegments: s.timeline.length }; },
    stallKey(s) { return JSON.stringify({ ready: s.ready, running: s.running, tasks: s.tasks.map(task => [task.pid,task.remaining,task.completion,task.requeueOnNextStep]), arrivals: s.tasks.filter(task => task.completion === null && task.arrival >= s.t).map(task => task.arrival - s.t) }); },
    isDeadlocked(s) { return !s.ready.length && !s.running && !s.switchRemaining && !s.tasks.some(task => (task.completion === null && task.arrival >= s.t) || task.requeueOnNextStep); },
    step(s) {
      const t = s.t;
      const events = [];
      for (const task of s.tasks) if (task.arrival === t && task.completion === null && !s.ready.includes(task.pid) && s.running !== task.pid) {
        task.readySince = t; task.readyOrder = s.enqueueCounter++; s.ready.push(task.pid);
        events.push({ t, type: 'ARRIVAL', actor: task.pid, detail: 'entered ready queue', reason: `${task.pid} arrived at t=${t} and joined the ready queue.` });
      }
      // At a Round Robin boundary, newly arrived tasks above enter first; only then is the expired task appended.
      const expired = s.tasks.find(task => task.requeueOnNextStep);
      if (expired) { s.ready.push(expired.pid); expired.readySince = t; expired.readyOrder = s.enqueueCounter++; expired.requeueOnNextStep = false; }
      const taskOf = pid => s.tasks.find(task => task.pid === pid);
      const policy = s.algorithm;
      const preemptive = ['SRTF', 'PRIORITY_PREEMPTIVE', 'PRIORITY_AGING', 'RR', 'MLFQ', 'EDF', 'RM'].includes(policy);
      const effectivePriority = task => Math.max(0, task.priority - (policy === 'PRIORITY_AGING' ? Math.floor(task.waiting / s.agingInterval) : 0));
      const orderedReady = () => [...s.ready].sort((a, b) => {
        const x = taskOf(a), y = taskOf(b);
        if (policy === 'SJF') return x.remaining - y.remaining || x.arrival - y.arrival || byPid(x, y);
        if (policy === 'SRTF') return x.remaining - y.remaining || x.arrival - y.arrival || byPid(x, y);
        if (policy.startsWith('PRIORITY')) return effectivePriority(x) - effectivePriority(y) || x.arrival - y.arrival || byPid(x, y);
        if (policy === 'EDF') return x.deadline - y.deadline || x.arrival - y.arrival || byPid(x, y);
        if (policy === 'RM') return x.period - y.period || x.arrival - y.arrival || byPid(x, y);
        if (policy === 'MLFQ') return x.queueLevel - y.queueLevel || x.readyOrder - y.readyOrder || byPid(x, y);
        return x.readyOrder - y.readyOrder || byPid(x, y);
      });

      if (s.running && preemptive && s.ready.length) {
        const current = taskOf(s.running), candidate = taskOf(orderedReady()[0]);
        const shouldPreempt = policy === 'SRTF' ? candidate.remaining < current.remaining
          : policy === 'EDF' ? candidate.deadline < current.deadline
            : policy === 'RM' ? candidate.period < current.period
              : policy.startsWith('PRIORITY') ? effectivePriority(candidate) < effectivePriority(current)
                : policy === 'MLFQ' ? candidate.queueLevel < current.queueLevel : false;
        if (shouldPreempt) {
          current.readySince = t; current.readyOrder = t; s.ready.push(current.pid); s.running = null;
          events.push({ t, type: 'PREEMPT', actor: current.pid, detail: `preempted by ${candidate.pid}`, reason: `${policy}: ${candidate.pid} outranks ${current.pid} under the selected scheduling rule, so ${current.pid} returns to READY.` });
        }
      }

      if (!s.running && !s.switchRemaining && s.ready.length) {
        const pid = orderedReady()[0];
        s.ready.splice(s.ready.indexOf(pid), 1);
        const next = taskOf(pid);
        if (s.previousPid && s.previousPid !== pid && s.switchCost > 0) {
          s.switchRemaining = s.switchCost;
          s.switches += 1;
          s.pendingPid = pid;
          s.timeline.push({ pid: null, start: t, end: t + s.switchCost, kind: 'SWITCH' });
          events.push({ t, type: 'CONTEXT_SWITCH', actor: pid, detail: `${s.switchCost} tick(s)`, reason: `The CPU pays the configured ${s.switchCost}-tick context-switch cost before running ${pid}.` });
          s.switchRemaining -= 1;
          return { state: { ...s, t: t + 1 }, events };
        }
        s.running = pid;
        if (next.firstStart === null) next.firstStart = t;
        next.waiting += Math.max(0, t - (next.readySince ?? t));
        events.push({ t, type: 'DISPATCH', actor: pid, detail: policy, reason: `${policy} selected ${pid} from the ready set using its configured ordering rule.` });
      }
      if (s.switchRemaining > 0) {
        s.switchRemaining -= 1;
        if (!s.switchRemaining && s.pendingPid) { const task = taskOf(s.pendingPid); s.running = task.pid; task.firstStart ??= t + 1; task.waiting += Math.max(0, t + 1 - (task.readySince ?? t + 1)); events.push({ t: t + 1, type: 'DISPATCH', actor: task.pid, detail: policy, reason: `${task.pid} begins after the context-switch interval.` }); s.pendingPid = null; }
        return { state: { ...s, t: t + 1 }, events };
      }

      const runningTask = s.running && taskOf(s.running);
      if (!runningTask) {
        if (s.tasks.some(task => task.completion === null && task.arrival > t)) {
          s.idle += 1; s.timeline.push({ pid: null, start: t, end: t + 1, kind: 'IDLE' });
          events.push({ t, type: 'IDLE', actor: null, detail: 'no process is ready', reason: `The CPU is idle at t=${t}; no process has arrived or is ready.` });
          return { state: { ...s, t: t + 1 }, events };
        }
        return { state: s, events };
      }
      const last = s.timeline.at(-1);
      if (last?.kind === 'RUN' && last.pid === runningTask.pid && last.end === t) last.end += 1;
      else s.timeline.push({ pid: runningTask.pid, start: t, end: t + 1, kind: 'RUN' });
      runningTask.remaining -= 1; runningTask.executed += 1; runningTask.quantumUsed += 1; s.busy += 1;
      events.push({ t: t + 1, type: 'CPU_TICK', actor: runningTask.pid, detail: `remaining=${runningTask.remaining}`, reason: `${runningTask.pid} used one CPU tick; ${runningTask.remaining} tick(s) remain.` });
      if (runningTask.remaining === 0) {
        runningTask.completion = t + 1; s.completed.push(runningTask.pid); s.previousPid = runningTask.pid; s.running = null;
        events.push({ t: t + 1, type: 'TERMINATE', actor: runningTask.pid, detail: 'burst complete', reason: `${runningTask.pid} completed its CPU burst at t=${t + 1}.` });
      } else if (policy === 'RR' && runningTask.quantumUsed >= s.quantum) {
          runningTask.quantumUsed = 0; runningTask.readySince = t + 1; s.running = null;
        // Arrivals at the boundary were queued at the start of the next step before this process is requeued.
        runningTask.requeueOnNextStep = true;
        s.previousPid = runningTask.pid;
        events.push({ t: t + 1, type: 'QUANTUM_EXPIRED', actor: runningTask.pid, detail: `quantum=${s.quantum}`, reason: `${runningTask.pid}'s Round Robin quantum expired; boundary-time arrivals are enqueued before it is requeued.` });
      } else if (policy === 'MLFQ' && runningTask.quantumUsed >= [2, 4, 8][Math.min(runningTask.queueLevel, 2)]) {
        runningTask.quantumUsed = 0; runningTask.queueLevel = Math.min(2, runningTask.queueLevel + 1); runningTask.readySince = t + 1; runningTask.readyOrder = t + 1; s.running = null; s.ready.push(runningTask.pid); s.previousPid = runningTask.pid;
        events.push({ t: t + 1, type: 'QUEUE_DEMOTION', actor: runningTask.pid, detail: `level=${runningTask.queueLevel}`, reason: `${runningTask.pid} exhausted its MLFQ quantum and moved down to queue ${runningTask.queueLevel}.` });
      }
      for (const task of s.tasks) if (s.ready.includes(task.pid)) task.waiting += 1;
      // Deferred requeue is appended after next-step arrivals (see the top of step()).
      return { state: { ...s, t: t + 1 }, events };
    },
    metrics(s) {
      const rows = s.tasks.map(task => ({ pid: task.pid, arrival: task.arrival, burst: task.burst, priority: task.priority, start: task.firstStart,
        completion: task.completion, turnaround: task.completion === null ? null : task.completion - task.arrival,
        waiting: task.completion === null ? task.waiting : task.completion - task.arrival - task.burst,
        response: task.firstStart === null ? null : task.firstStart - task.arrival,
        deadlineMissed: Number.isFinite(task.deadline) && task.completion !== null && task.completion > task.deadline }));
      const done = rows.filter(row => row.completion !== null), elapsed = s.t;
      const mean = key => done.length ? done.reduce((sum, row) => sum + row[key], 0) / done.length : 0;
      const periodic = s.periodicTasks.filter(task=>Number.isFinite(task.period)&&task.period>0);
      const n = periodic.length, utilization = n ? periodic.reduce((sum, task) => sum + task.burst / task.period, 0) : 0;
      const bound = n ? n * (2 ** (1 / n) - 1) : 0;
      const claims = { FCFS: 'FCFS preserves arrival order; it does not minimise waiting time in general.', SJF: 'Minimises average waiting time only when all jobs are available at t=0 and burst lengths are known.', SRTF: 'Minimises average waiting time for a known workload with preemption and no context-switch cost.', RR: 'Improves response sharing with a fixed quantum; it does not minimise turnaround time.', PRIORITY: 'Selects the smallest numeric priority; low-priority work can starve.', PRIORITY_PREEMPTIVE: 'Preempts for a smaller numeric priority; low-priority work can starve.', PRIORITY_AGING: 'Aging raises waiting work gradually; it reduces starvation under finite arrivals.', MLFQ: 'Favors short/interactive work using feedback queues; its outcome depends on the configured queue policy.', EDF: 'Optimal among preemptive uniprocessor schedulers for independent jobs with deadlines and no overhead.', RM: 'Fixed-priority preemptive policy; utilization bound is sufficient, not necessary.' };
      return { timeline: s.timeline, perTask: rows, averageWaiting: mean('waiting'), averageTurnaround: mean('turnaround'), averageResponse: mean('response'),
        cpuUtilisation: elapsed ? s.busy / elapsed : 0, throughput: elapsed ? done.length / elapsed : 0, contextSwitches: s.switches,
        starved: rows.filter(row => row.start === null).map(row => row.pid), preemptive: ['SRTF','PRIORITY_PREEMPTIVE','PRIORITY_AGING','RR','MLFQ','EDF','RM'].includes(s.algorithm),
        optimalityClaim: claims[s.algorithm] || claims.FCFS, missedDeadlines: rows.filter(row => row.deadlineMissed).map(row => row.pid),
        rateMonotonic: s.algorithm === 'RM' ? { utilization, bound, passesSufficientBound: utilization <= bound, sufficientNotNecessary: true } : null };
    },
  };
}

export function simulateScheduling({ workload, algorithm = 'FCFS', quantum = 2, contextSwitchCost = 0, agingInterval = 3, seed = 1, maxSteps = 10000 }) {
  return runSimulation({ model: createSchedulingModel(), workload, params: { algorithm, quantum, contextSwitchCost, agingInterval }, seed, maxSteps });
}
import { runSimulation } from './kernel/index.js';
