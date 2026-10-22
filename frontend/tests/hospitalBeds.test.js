import test from 'node:test';
import assert from 'node:assert/strict';
import { erlangB, erlangC, mmcK, priorityWaits, bedsForBlockingTarget, fluidOccupancy, simulateBeds, replicate, analyseHospital, admissionSafety, bedRisk } from '../src/modules/os-labs/hospitalBeds.js';
import { bankerSafeSequence } from '../src/osAlgorithms.js';

const close = (actual, expected, tolerance, label) => assert.ok(Math.abs(actual - expected) <= tolerance, `${label}: ${actual} vs ${expected}`);

test('Erlang-B matches published values', () => {
  close(erlangB(1, 2), 2 / 3, 1e-12, 'B(1,2)');
  close(erlangB(10, 5), 0.018385, 1e-5, 'B(10,5)');
  close(erlangB(20, 15), 0.0456, 1e-3, 'B(20,15)');
  assert.equal(erlangB(0, 3), 1);
});

test('Erlang-C reduces correctly and saturates when unstable', () => {
  close(erlangC(2, 1), 1 / 3, 1e-12, 'C(2,1)');
  close(erlangC(1, 0.5), 0.5, 1e-12, 'C(1,0.5) equals rho');
  assert.equal(erlangC(3, 3), 1);
});

test('M/M/1/K closed form', () => {
  const rho = 0.8, K = 5;
  const expected = ((1 - rho) * rho ** K) / (1 - rho ** (K + 1));
  const model = mmcK(0.8, 1, 1, K);
  close(model.blocking, expected, 1e-12, 'blocking');
  close(model.p.reduce((s, v) => s + v, 0), 1, 1e-12, 'probabilities sum to 1');
});

test('M/M/c/c has the Erlang-B blocking probability', () => {
  close(mmcK(5, 1, 10, 10).blocking, erlangB(10, 5), 1e-12, 'K=c');
});

test('Little law and busy-bed identity hold', () => {
  const model = mmcK(4, 0.5, 10, 14);
  close(model.meanInSystem, model.lambdaEff * model.meanStayHours, 1e-9, 'L = lambda_eff W');
  close(model.meanBedsBusy, model.lambdaEff / 0.5, 1e-9, 'busy beds = lambda_eff / mu');
  close(model.utilisation, model.meanBedsBusy / 10, 1e-12, 'utilisation');
});

test('priority waits: one class equals the Erlang-C wait; critical class waits less', () => {
  const [single] = priorityWaits([3], 0.5, 8);
  close(single, erlangC(8, 6) / (8 * 0.5 - 3), 1e-12, 'single class');
  const [urgent, minor] = priorityWaits([1.5, 1.5], 0.5, 8);
  assert.ok(urgent < single && single < minor, 'urgent < pooled < minor');
  const rate = 3, capacity = 4;
  const weighted = (urgent * 1.5 + minor * 1.5) / rate; // conservation law for equal service rates
  close(weighted, single, 1e-12, 'work-conserving average');
  assert.deepEqual(priorityWaits([5], 0.5, 8), [Infinity]);
});

test('bed sizing returns the minimum beds meeting the target', () => {
  const beds = bedsForBlockingTarget(5, 1, 0, 0.01);
  assert.ok(mmcK(5, 1, beds, beds).blocking <= 0.01);
  assert.ok(mmcK(5, 1, beds - 1, beds - 1).blocking > 0.01);
});

test('fluid model approaches steady demand and reports time to saturation', () => {
  const result = fluidOccupancy(10, 0.25, 20, 24, 30); // steady demand 40 beds > 30
  assert.equal(result.steadyDemandBeds, 40);
  close(20 + (40 - 20) * (1 - Math.exp(-0.25 * result.hoursToFull)), 30, 1e-9, 'trajectory hits capacity at hoursToFull');
  assert.equal(fluidOccupancy(1, 0.25, 2, 10, 30).hoursToFull, null);
});

test('simulation agrees with the exact model within sampling error', () => {
  const lambda = 4, mu = 0.5, beds = 9, capacity = 11;
  const exact = mmcK(lambda, mu, beds, capacity);
  const sim = replicate({ lambda, mu, beds, capacity, hours: 3000, warmup: 100, seed: 11 }, 30);
  close(sim.divertedFraction, exact.blocking, Math.max(0.01, 3 * sim.divertedHalfWidth95), 'diversion');
  close(sim.utilisation, exact.utilisation, 0.03, 'utilisation');
  close(sim.meanWaitHours, exact.meanWaitHours, 0.15 * Math.max(0.2, exact.meanWaitHours) + 0.05, 'wait');
});

test('simulation is deterministic per seed and records semaphore events', () => {
  const a = simulateBeds({ lambda: 2, mu: 0.5, beds: 3, capacity: 5, hours: 50, seed: 7, traceLimit: 10 });
  const b = simulateBeds({ lambda: 2, mu: 0.5, beds: 3, capacity: 5, hours: 50, seed: 7, traceLimit: 10 });
  assert.deepEqual(a, b);
  assert.ok(a.trace.every(row => ['ADMIT', 'QUEUE', 'DIVERT', 'DISCHARGE'].includes(row.type)));
});

test('hospital analysis returns risk with weights summing to one and surge worse than baseline', () => {
  const report = analyseHospital({ icuBeds: 8, wardBeds: 40, icuBoarding: 2, wardBoarding: 10, icuStayHours: 48, wardStayHours: 12, icuArrivalsPerHour: 0.12, urgentArrivalsPerHour: 1.2, minorArrivalsPerHour: 1.6, icuOccupied: 5, wardOccupied: 30, surgeMultiplier: 3, surgeHours: 12, seed: 5 });
  for (const risk of [report.icu.risk, report.ward.risk, report.surge.risk]) {
    close(risk.factors.reduce((s, f) => s + f.weight, 0), 1, 1e-9, 'weights');
    close(risk.score, risk.factors.reduce((s, f) => s + f.points, 0), 0.2, 'score equals points');
  }
  assert.ok(report.surge.ward.blocking >= report.ward.blocking);
  assert.ok(report.ward.priorityWaitMinutes.urgent <= report.ward.priorityWaitMinutes.minor);
  close(report.ward.simulated.divertedFraction, report.ward.blocking, 0.02, 'sim vs exact (ward)');
  assert.ok(report.trace.length > 0);
});

test('risk bands and Banker admission safety', () => {
  assert.equal(bedRisk({ blocking: 0, utilisation: 0.3, criticalWaitMinutes: 0, shortfallBeds: 0 }).band, 'LOW');
  assert.equal(bedRisk({ blocking: 0.2, utilisation: 1, criticalWaitMinutes: 30, shortfallBeds: 20 }).band, 'SEVERE');
  const maximum = [[2, 1, 2], [1, 1, 1], [2, 0, 2]], allocation = [[1, 0, 1], [0, 1, 0], [1, 0, 1]];
  assert.equal(admissionSafety(bankerSafeSequence, [1, 1, 1], allocation, maximum, ['A', 'B', 'C']).safe, true);
  assert.equal(admissionSafety(bankerSafeSequence, [0, 0, 0], allocation, maximum, ['A', 'B', 'C']).safe, false);
});
