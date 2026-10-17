export function scheduleTasks(tasks, algorithm = 'FCFS', quantum = 1) {
  const remaining = Object.fromEntries(tasks.map(task => [task.id, task.burst]));
  const firstStart = {}, completion = {}, gantt = [], ready = [];
  const waitingToArrive = [...tasks].sort((a, b) => a.arrival - b.arrival);
  let now = 0;
  while (Object.keys(completion).length < tasks.length) {
    while (waitingToArrive.length && waitingToArrive[0].arrival <= now) ready.push(waitingToArrive.shift().id);
    if (!ready.length) { now = waitingToArrive[0].arrival; continue; }
    let index = 0;
    if (algorithm === 'SJF') index = ready.reduce((best, id, i) => remaining[id] < remaining[ready[best]] ? i : best, 0);
    const id = ready.splice(index, 1)[0], task = tasks.find(item => item.id === id);
    firstStart[id] ??= now;
    const duration = algorithm === 'RR' ? Math.min(remaining[id], Math.max(1, Number(quantum))) : remaining[id];
    const start = now;
    now += duration;
    remaining[id] -= duration;
    gantt.push({ id, name: task.name, start, end: now });
    while (waitingToArrive.length && waitingToArrive[0].arrival <= now) ready.push(waitingToArrive.shift().id);
    if (remaining[id] > 0) ready.push(id); else completion[id] = now;
  }
  return {
    gantt,
    rows: tasks.map(task => ({ ...task, completion: completion[task.id], turnaround: completion[task.id] - task.arrival, waiting: completion[task.id] - task.arrival - task.burst, response: firstStart[task.id] - task.arrival }))
  };
}

export function bankerSafeSequence(available, allocation, maximum) {
  const need = allocation.map((row, i) => row.map((value, j) => maximum[i][j] - value));
  const work = [...available], finished = allocation.map(() => false), order = [], workTrace = [{ process: null, work: [...work] }];
  let progressed = true;
  while (progressed) {
    progressed = false;
    for (let i = 0; i < allocation.length; i += 1) if (!finished[i] && need[i].every((value, j) => value <= work[j])) {
      work.forEach((_, j) => { work[j] += allocation[i][j]; });
      finished[i] = true; order.push(`P${i}`); workTrace.push({ process: `P${i}`, work: [...work] }); progressed = true;
    }
  }
  return { safe: finished.every(Boolean), order, need, workTrace };
}

export function evaluateBankerRequest(available, allocation, maximum, processIndex, request) {
  const current = bankerSafeSequence(available, allocation, maximum);
  if (request.some((value, j) => value < 0 || value > current.need[processIndex][j])) return { granted: false, message: 'Denied: request exceeds the process remaining Need.' };
  if (request.some((value, j) => value > available[j])) return { granted: false, message: 'Wait: requested resource exceeds Available.' };
  const nextAvailable = available.map((value, j) => value - request[j]);
  const nextAllocation = allocation.map((row, i) => i === processIndex ? row.map((value, j) => value + request[j]) : [...row]);
  const result = bankerSafeSequence(nextAvailable, nextAllocation, maximum);
  if (!result.safe) return { granted: false, message: 'Denied: tentative allocation would leave the system unsafe.', ...result };
  return { granted: true, message: 'Granted: tentative allocation keeps the system safe.', available: nextAvailable, allocation: nextAllocation, ...result };
}
