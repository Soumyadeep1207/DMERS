import { runSimulation } from '../kernel/index.js';
import { createSchedulingModel } from '../scheduling.js';
import { createProcessModel } from '../processModel.js';
import { runLabTask } from '../runLabTask.js';

self.addEventListener('message', event => {
  const { id, model, workload, params, seed, maxSteps } = event.data;
  try {
    const result = model === 'lab' ? runLabTask(event.data.kind, event.data.inputs) : runSimulation({ model: model === 'process' ? createProcessModel() : createSchedulingModel(), workload, params, seed, maxSteps });
    self.postMessage({ id, result });
  } catch (error) {
    self.postMessage({ id, error: error instanceof Error ? error.message : String(error) });
  }
});
