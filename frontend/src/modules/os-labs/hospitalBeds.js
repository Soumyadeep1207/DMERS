/**
 * Hospital bed management as an operating-systems resource problem.
 *
 * A pool of c identical beds is a counting semaphore: admit = P(wait), discharge = V(signal),
 * and patients who cannot get a bed either queue (boarding) or are diverted (blocked).
 * Steady-state behaviour uses exact queueing theory rather than rules of thumb:
 *
 *   a = lambda / mu                 offered load in beds (Erlangs); lambda = arrivals/h, 1/mu = mean stay (h)
 *   Erlang-B  B(c, a)               probability all c beds are busy when no waiting is allowed
 *   Erlang-C  C(c, a)               probability an arrival must wait when waiting is unlimited (needs a < c)
 *   M/M/c/K   exact P_n             c beds plus K - c boarding places; arrivals who find K in system are diverted
 *   Cobham-type priority waits      equal-mu non-preemptive priority classes (critical patients jump the queue)
 *
 * Assumptions (stated so results are not over-read): Poisson arrivals, exponential length of stay,
 * identical beds, no reneging, stationary rates. Real stays are heavier-tailed, so treat outputs as
 * planning estimates; the Monte-Carlo cross-check shows how closely a simulation agrees with the formulas.
 */
import { mulberry32 } from './kernel/index.js';

export function erlangB(servers, offered) {
  if (!Number.isInteger(servers) || servers < 0 || offered < 0) throw new RangeError('servers must be a whole number and offered load non-negative');
  let b = 1;
  for (let k = 1; k <= servers; k += 1) b = (offered * b) / (k + offered * b);
  return b;
}

export function erlangC(servers, offered) {
  if (servers < 1) throw new RangeError('Erlang-C needs at least one server');
  const rho = offered / servers;
  if (rho >= 1) return 1; // unstable: every arrival eventually waits
  const b = erlangB(servers, offered);
  return b / (1 - rho * (1 - b));
}

/** Exact steady state of M/M/c/K. `capacity` is K = beds + boarding places (K >= c). */
export function mmcK(lambda, mu, servers, capacity) {
  if (!(lambda >= 0) || !(mu > 0)) throw new RangeError('lambda must be >= 0 and mu must be > 0');
  if (!Number.isInteger(servers) || servers < 1) throw new RangeError('servers must be a whole number >= 1');
  if (!Number.isInteger(capacity) || capacity < servers) throw new RangeError('capacity must be a whole number >= servers');
  const a = lambda / mu;
  const weights = [1]; // unnormalised P_n / P_0, built from the ratio P_n / P_{n-1} = a / min(n, c)
  for (let n = 1; n <= capacity; n += 1) weights.push(weights[n - 1] * a / Math.min(n, servers));
  const total = weights.reduce((sum, value) => sum + value, 0);
  const p = weights.map(value => value / total);
  const blocking = p[capacity];
  const lambdaEff = lambda * (1 - blocking);
  let L = 0, Lq = 0;
  p.forEach((value, n) => { L += n * value; Lq += Math.max(0, n - servers) * value; });
  const pWait = lambdaEff > 0 ? p.slice(servers, capacity).reduce((s, v) => s + v, 0) / (1 - blocking) : 0; // PASTA, admitted arrivals only
  const busy = L - Lq;
  return {
    offeredLoad: a, p, blocking, lambdaEff, diverted: lambda - lambdaEff,
    meanInSystem: L, meanQueue: Lq, meanBedsBusy: busy, utilisation: busy / servers, freeBedsExpected: servers - busy,
    pWait, meanWaitHours: lambdaEff > 0 ? Lq / lambdaEff : 0, meanStayHours: lambdaEff > 0 ? L / lambdaEff : 0,
    pAllBedsBusy: p.slice(servers).reduce((s, v) => s + v, 0),
  };
}

/** Smallest bed count whose diversion probability is at or below `target`; searches up to `limit` beds. */
export function bedsForBlockingTarget(lambda, mu, boardingPlaces, target, limit = 2000) {
  for (let beds = 1; beds <= limit; beds += 1) if (mmcK(lambda, mu, beds, beds + boardingPlaces).blocking <= target) return beds;
  return null;
}

/**
 * Mean queueing delay (hours) per priority class for an M/M/c queue with a common service rate mu and
 * non-preemptive priority; class 0 is highest. W_k = C(c,a) / (c mu (1 - sigma_{k-1})(1 - sigma_k)),
 * sigma_k = (lambda_0 + ... + lambda_k) / (c mu). Reduces to the plain Erlang-C wait for one class.
 */
export function priorityWaits(lambdas, mu, servers) {
  const total = lambdas.reduce((s, v) => s + v, 0);
  const capacity = servers * mu;
  if (total >= capacity) return lambdas.map(() => Infinity);
  const wait = erlangC(servers, total / mu);
  let cumulative = 0;
  return lambdas.map(rate => {
    const before = cumulative / capacity;
    cumulative += rate;
    return wait / (capacity * (1 - before) * (1 - cumulative / capacity));
  });
}

/** Deterministic-mean (fluid) occupancy after a step change in arrivals: N(t) = N_inf + (N0 - N_inf) e^(-mu t). */
export function fluidOccupancy(lambda, mu, startOccupied, hours, beds) {
  const inf = lambda / mu;
  const at = t => inf + (startOccupied - inf) * Math.exp(-mu * t);
  const saturates = inf > beds && startOccupied < beds;
  return { steadyDemandBeds: inf, hoursToFull: saturates ? -Math.log((inf - beds) / (inf - startOccupied)) / mu : startOccupied >= beds ? 0 : null,
    trajectory: Array.from({ length: Math.max(2, Math.round(hours) + 1) }, (_, h) => ({ hour: h, occupied: Math.min(at(h), Math.max(beds, startOccupied)) })) };
}

const exponential = (rng, rate) => -Math.log(1 - rng()) / rate;

/**
 * Event-driven M/M/c/K run (FIFO). Returns measured diversion rate, wait and utilisation plus the first
 * `traceLimit` semaphore events, so the OS view of admit/queue/divert/discharge is visible.
 */
export function simulateBeds({ lambda, mu, beds, capacity, hours, seed = 1, traceLimit = 40, warmup = 0 }) {
  const rng = mulberry32(seed);
  let t = 0, nextArrival = exponential(rng, lambda);
  const stays = []; // completion times of beds in use
  const queue = []; // arrival times of boarded patients
  let arrivals = 0, diverted = 0, admitted = 0, waitSum = 0, waitCount = 0, busyArea = 0, lastT = 0, peakQueue = 0;
  const trace = [];
  const log = (type, detail) => { if (trace.length < traceLimit) trace.push({ t: +t.toFixed(2), type, detail, free: beds - stays.length, queue: queue.length }); };
  const end = hours;
  const advance = to => { busyArea += stays.length * Math.max(0, to - Math.max(lastT, warmup)); lastT = to; };
  while (true) {
    const nextDischarge = stays.length ? Math.min(...stays) : Infinity;
    const eventTime = Math.min(nextArrival, nextDischarge);
    if (eventTime > end) { advance(end); break; }
    advance(eventTime);
    t = eventTime;
    if (nextDischarge <= nextArrival) {
      stays.splice(stays.indexOf(nextDischarge), 1);
      log('DISCHARGE', 'bed released (signal)');
      if (queue.length) {
        const arrived = queue.shift();
        stays.push(t + exponential(rng, mu)); admitted += 1;
        if (t >= warmup) { waitSum += t - arrived; waitCount += 1; }
        log('ADMIT', 'boarded patient takes the freed bed');
      }
    } else {
      nextArrival = t + exponential(rng, lambda);
      const counted = t >= warmup;
      if (counted) arrivals += 1;
      if (stays.length < beds) { stays.push(t + exponential(rng, mu)); admitted += 1; if (counted) waitCount += 1; log('ADMIT', 'bed acquired immediately (wait)'); }
      else if (queue.length < capacity - beds) { queue.push(t); peakQueue = Math.max(peakQueue, queue.length); log('QUEUE', 'all beds busy; patient boards in ED'); }
      else { if (counted) diverted += 1; log('DIVERT', 'system full; ambulance diverted'); }
    }
  }
  const span = Math.max(1e-9, end - warmup);
  return { arrivals, diverted, divertedFraction: arrivals ? diverted / arrivals : 0, meanWaitHours: waitCount ? waitSum / waitCount : 0,
    utilisation: busyArea / (span * beds), peakQueue, admitted, trace };
}

/** Average several independent seeded replications: returns means and a 95% half-width for diversion probability. */
export function replicate(params, replications = 40) {
  const runs = Array.from({ length: replications }, (_, i) => simulateBeds({ ...params, seed: params.seed + i * 7919, traceLimit: 0 }));
  const mean = key => runs.reduce((s, r) => s + r[key], 0) / runs.length;
  const m = mean('divertedFraction');
  const variance = runs.reduce((s, r) => s + (r.divertedFraction - m) ** 2, 0) / Math.max(1, runs.length - 1);
  return { replications, divertedFraction: m, divertedHalfWidth95: 1.96 * Math.sqrt(variance / runs.length), meanWaitHours: mean('meanWaitHours'), utilisation: mean('utilisation') };
}

/** Weighted-factor risk with the same transparency as the backend route risk. */
export function bedRisk({ blocking, utilisation, criticalWaitMinutes, shortfallBeds, toleranceMinutes = 15 }) {
  const clamp = v => Math.max(0, Math.min(1, v));
  const factors = [
    ['Chance an arriving patient is diverted', blocking, `${(blocking * 100).toFixed(1)}%`, clamp(blocking / 0.1), 0.40, 'P(system full) from the exact M/M/c/K model; 10% saturates.'],
    ['Bed utilisation pressure', utilisation, `${(utilisation * 100).toFixed(0)}%`, clamp((utilisation - 0.7) / 0.3), 0.25, 'Below 70% busy adds no pressure; 100% saturates.'],
    ['Wait for the highest-priority patient', criticalWaitMinutes, `${criticalWaitMinutes.toFixed(1)} min`, clamp(criticalWaitMinutes / toleranceMinutes), 0.20, `Unlimited-queue mean wait for the top priority class; ${toleranceMinutes} min is the assumed tolerance that saturates the factor.`],
    ['Bed shortfall to meet the 1% diversion target', shortfallBeds, `${shortfallBeds} beds`, clamp(shortfallBeds / 10), 0.15, 'Additional beds needed for <= 1% diversion; 10 beds saturates.'],
  ].map(([name, raw, display, normalised, weight, note]) => ({ name, value: display, raw, normalised: +normalised.toFixed(3), weight, points: +(100 * weight * normalised).toFixed(1), note }));
  const score = +Math.min(100, factors.reduce((s, f) => s + f.points, 0)).toFixed(1);
  const band = score < 20 ? 'LOW' : score < 40 ? 'MODERATE' : score < 65 ? 'HIGH' : 'SEVERE';
  return { score, band, formula: 'score = 100 x sum(weight x normalised factor); bands: <20 LOW, <40 MODERATE, <65 HIGH, else SEVERE', factors,
    assumptions: ['Poisson arrivals and exponential length of stay; real stays are heavier-tailed.', 'Rates are treated as constant over the planning window.', 'A decision-support indicator, not a clinical safety guarantee.'] };
}

/**
 * Full hospital analysis used by the OS laboratory: ICU pool for critical patients, ward pool for
 * urgent + minor patients with priority, an exact-vs-simulated cross-check, bed sizing, and a surge forecast.
 */
export function analyseHospital(input) {
  const n = key => { const v = Number(input[key]); if (!Number.isFinite(v)) throw new RangeError(`${key} must be a number`); return v; };
  const icuBeds = Math.round(n('icuBeds')), wardBeds = Math.round(n('wardBeds'));
  const icuBoard = Math.round(n('icuBoarding')), wardBoard = Math.round(n('wardBoarding'));
  const icuLos = n('icuStayHours'), wardLos = n('wardStayHours');
  const lamIcu = n('icuArrivalsPerHour'), lamUrgent = n('urgentArrivalsPerHour'), lamMinor = n('minorArrivalsPerHour');
  const occupiedIcu = n('icuOccupied'), occupiedWard = n('wardOccupied');
  const surgeX = n('surgeMultiplier'), surgeHours = n('surgeHours');
  if (icuBeds < 1 || wardBeds < 1 || icuBoard < 0 || wardBoard < 0) throw new RangeError('Bed and boarding counts must be positive whole numbers');
  if (icuLos <= 0 || wardLos <= 0 || lamIcu < 0 || lamUrgent < 0 || lamMinor < 0) throw new RangeError('Stay lengths must be positive and arrival rates non-negative');
  const seed = Number(input.seed) || 1;
  const muIcu = 1 / icuLos, muWard = 1 / wardLos, lamWard = lamUrgent + lamMinor;
  const icu = mmcK(lamIcu, muIcu, icuBeds, icuBeds + icuBoard);
  const ward = mmcK(lamWard, muWard, wardBeds, wardBeds + wardBoard);
  const wardWaits = priorityWaits([lamUrgent, lamMinor], muWard, wardBeds);
  const icuWaitC = lamIcu / muIcu < icuBeds ? priorityWaits([lamIcu], muIcu, icuBeds)[0] : Infinity;
  const sized = (lam, mu, board) => bedsForBlockingTarget(lam, mu, board, 0.01);
  const icuNeeded = sized(lamIcu, muIcu, icuBoard), wardNeeded = sized(lamWard, muWard, wardBoard);
  const params = pool => ({ ...pool, seed, hours: 4000, warmup: 200 });
  const icuSim = replicate(params({ lambda: lamIcu, mu: muIcu, beds: icuBeds, capacity: icuBeds + icuBoard }), 25);
  const wardSim = replicate(params({ lambda: lamWard, mu: muWard, beds: wardBeds, capacity: wardBeds + wardBoard }), 25);
  const surgeIcu = mmcK(lamIcu * surgeX, muIcu, icuBeds, icuBeds + icuBoard);
  const surgeWard = mmcK(lamWard * surgeX, muWard, wardBeds, wardBeds + wardBoard);
  const trace = simulateBeds({ lambda: lamIcu * surgeX + 0.0001, mu: muIcu, beds: Math.min(icuBeds, 6), capacity: Math.min(icuBeds, 6) + 2, hours: Math.max(24, surgeHours), seed, traceLimit: 28 });
  const ward0 = Math.min(occupiedWard, wardBeds), icu0 = Math.min(occupiedIcu, icuBeds);
  const finite = v => (Number.isFinite(v) ? v : 999);
  const icuRisk = bedRisk({ toleranceMinutes: 60, blocking: icu.blocking, utilisation: icu.utilisation, criticalWaitMinutes: finite(icuWaitC) * 60, shortfallBeds: Math.max(0, (icuNeeded ?? icuBeds + 10) - icuBeds) });
  const wardRisk = bedRisk({ toleranceMinutes: 30, blocking: ward.blocking, utilisation: ward.utilisation, criticalWaitMinutes: finite(wardWaits[0]) * 60, shortfallBeds: Math.max(0, (wardNeeded ?? wardBeds + 10) - wardBeds) });
  const surgeRisk = bedRisk({ toleranceMinutes: 30, blocking: surgeWard.blocking, utilisation: surgeWard.utilisation, criticalWaitMinutes: finite(priorityWaits([lamUrgent * surgeX, lamMinor * surgeX], muWard, wardBeds)[0]) * 60, shortfallBeds: Math.max(0, (sized(lamWard * surgeX, muWard, wardBoard) ?? wardBeds + 10) - wardBeds) });
  return {
    inputs: { icuBeds, wardBeds, icuBoard, wardBoard, icuLos, wardLos, lamIcu, lamUrgent, lamMinor, surgeX, surgeHours },
    icu: { ...icu, p: undefined, risk: icuRisk, bedsNeededForOnePercent: icuNeeded, erlangB: erlangB(icuBeds, lamIcu / muIcu), criticalWaitMinutes: icuWaitC * 60, simulated: icuSim },
    ward: { ...ward, p: undefined, risk: wardRisk, bedsNeededForOnePercent: wardNeeded, erlangB: erlangB(wardBeds, lamWard / muWard), simulated: wardSim,
      priorityWaitMinutes: { urgent: wardWaits[0] * 60, minor: wardWaits[1] * 60 } },
    surge: { multiplier: surgeX, hours: surgeHours, ward: { ...surgeWard, p: undefined }, icu: { ...surgeIcu, p: undefined }, risk: surgeRisk,
      fluidWard: fluidOccupancy(lamWard * surgeX, muWard, ward0, surgeHours, wardBeds), fluidIcu: fluidOccupancy(lamIcu * surgeX, muIcu, icu0, surgeHours, icuBeds) },
    trace: trace.trace,
  };
}

/**
 * Multi-resource admission safety: admitting a patient group is allowed only if the Banker's safe-state
 * test still finds an order in which everyone can finish (no ward bed held while waiting forever for a ventilator).
 */
export function admissionSafety(bankerSafeSequence, available, allocation, maximum, labels) {
  const safe = bankerSafeSequence(available, allocation, maximum);
  return { safe: safe.safe, order: safe.safe ? safe.order.map(i => labels[i]) : [], need: safe.need };
}
