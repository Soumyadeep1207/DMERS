let nextId = 1;
import { runSimulation } from '../kernel/index.js';
import { createSchedulingModel } from '../scheduling.js';
import { createProcessModel } from '../processModel.js';
export function runInWorker(payload) {
  if (typeof Worker === 'undefined') return payload.model === 'lab'
    ? import('../runLabTask.js').then(({ runLabTask }) => runLabTask(payload.kind, payload.inputs))
    : Promise.resolve(runSimulation({ ...payload, model: payload.model === 'process' ? createProcessModel() : createSchedulingModel() }));
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL('./osWorker.js', import.meta.url), { type: 'module' });
    const id = nextId++;
    worker.onmessage = event => { worker.terminate(); event.data.error ? reject(new Error(event.data.error)) : resolve(event.data.result); };
    worker.onerror = event => { worker.terminate(); reject(new Error(event.message || 'OS simulation worker failed.')); };
    worker.postMessage({ ...payload, id });
  });
}
