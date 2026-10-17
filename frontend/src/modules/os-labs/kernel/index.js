/** Pure deterministic discrete-event runner. Models own all domain rules. */
export function mulberry32(seed = 1) {
  let state = Number(seed) >>> 0;
  return () => {
    state = (state + 0x6D2B79F5) >>> 0;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

const clone = value => structuredClone(value);

/**
 * Runs a model to completion once, retaining immutable-by-convention snapshots
 * for scrubbing. step() must return { state, events }; no wall-clock access is
 * available to a model through this interface.
 */
export function runSimulation({ model, workload = [], params = {}, seed = 1, maxSteps = 10000 }) {
  if (!model || !['init', 'step', 'isFinished', 'metrics'].every(key => typeof model[key] === 'function')) {
    throw new TypeError('A model must implement init, step, isFinished, and metrics.');
  }
  if (!Number.isInteger(maxSteps) || maxSteps < 1) throw new RangeError('maxSteps must be a positive integer.');
  const rng = mulberry32(seed);
  let state = model.init({ workload: clone(workload), params: clone(params), seed, rng });
  const capture = value => model.snapshot ? model.snapshot(value) : clone(value);
  const events = [];
  const snapshots = [capture(state)];
  const log = [];
  let status = 'COMPLETED';
  let repeatedStates = 0;
  let previousFingerprint = model.stallKey ? model.stallKey(state) : JSON.stringify(state);
  let steps = 0;

  while (!model.isFinished(state)) {
    if (steps >= maxSteps) { status = 'STEP_LIMIT'; break; }
    if (model.isDeadlocked?.(state)) { status = 'DEADLOCK'; break; }
    const transition = model.step(state, { t: steps, rng });
    if (!transition || !('state' in transition)) throw new TypeError('model.step must return { state, events }.');
    state = transition.state;
    const emitted = (transition.events || []).map(event => ({
      t: Number.isFinite(event.t) ? event.t : steps,
      type: event.type || 'STEP',
      actor: event.actor ?? null,
      detail: event.detail ?? '',
      reason: event.reason || 'The model advanced one deterministic simulation step.',
    }));
    events.push(...emitted);
    log.push(...emitted.map(event => event.reason));
    snapshots.push(capture(state));
    const fingerprint = model.stallKey ? model.stallKey(state) : JSON.stringify(state);
    repeatedStates = fingerprint === previousFingerprint ? repeatedStates + 1 : 0;
    if (repeatedStates >= (model.livelockLimit || 100)) { status = 'LIVELOCK'; break; }
    previousFingerprint = fingerprint;
    steps += 1;
  }
  return { events, snapshots, metrics: model.metrics(state, { events, steps, status }), log, status, steps, seed, finalState: clone(state) };
}
