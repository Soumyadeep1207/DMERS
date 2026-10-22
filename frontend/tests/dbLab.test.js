import test from 'node:test';
import assert from 'node:assert/strict';
import { daysBetween, describeEvent, fitPath, formatBytes, localToApi, matrixTone, parseSse, planBars, shortHash, speedup } from '../src/response/lab/labLogic.js';

test('server-sent events are split on blank lines and keep the unfinished tail', () => {
  const first = parseSse('retry: 3000\n\n: connected\n\ndata: {"table":"incidents","incident_id":3}\n\ndata: {"table":"disp');
  assert.deepEqual(first.events, [{ table: 'incidents', incident_id: 3 }]);
  assert.equal(first.rest, 'data: {"table":"disp');
  const second = parseSse(`${first.rest}atches","unit_id":2}\n\n`);
  assert.deepEqual(second.events, [{ table: 'dispatches', unit_id: 2 }]);
  assert.equal(second.rest, '');
  assert.deepEqual(parseSse('data: not json\n\n').events, []);           // a malformed message is dropped, not thrown
});

test('live events are described in plain language', () => {
  assert.equal(describeEvent({ table: 'incidents', op: 'INSERT', incident_id: 4, status: 'REPORTED', severity: 'MODERATE' }), 'Incident #4 reported (MODERATE)');
  assert.equal(describeEvent({ table: 'incidents', op: 'UPDATE', incident_id: 4, status: 'VERIFIED', severity: 'HIGH' }), 'Incident #4 is now VERIFIED (HIGH)');
  assert.equal(describeEvent({ table: 'dispatches', op: 'INSERT', incident_id: 9, unit_id: 2 }), 'Unit #2 dispatched to incident #9');
  assert.equal(describeEvent({ table: 'dispatches', op: 'UPDATE', incident_id: 9, unit_id: 2, status: 'ON_SCENE' }), 'Unit #2 is ON_SCENE at incident #9');
});

test('sizes, hashes and speed-ups are formatted for people', () => {
  assert.equal(formatBytes(null), '—');
  assert.equal(formatBytes(512), '512 B');
  assert.equal(formatBytes(24576), '24.0 KB');
  assert.equal(formatBytes(2260992), '2.16 MB');
  assert.equal(shortHash('584757709974fcc4106c21b9fa9dc225902b045cbef47273fda285538414c001'), '58475770…c001');
  assert.equal(shortHash(null), '(none: first entry)');
  assert.equal(speedup(56.45, 0.714), '79x');
  assert.equal(speedup(6.7, 1.03), '6.5x');
  assert.equal(speedup(0, 1), '—');
});

test('plan bars scale to the slowest node and never vanish', () => {
  const bars = planBars([{ ms: 10, loops: 1 }, { ms: 2.5, loops: 2 }, { ms: 0.001, loops: 1 }]);
  assert.deepEqual(bars.map(b => b.share), [100, 50, 2]);
  assert.deepEqual(planBars([{ ms: 0, loops: 1 }]).map(b => b.share), [2]);
});

test('a path is fitted north-up inside the box with the ground aspect ratio', () => {
  const { line, project } = fitPath([[12.90, 79.10], [12.94, 79.14]], 560, 320, 10);
  const [x0, y0] = project([12.90, 79.10]);
  const [x1, y1] = project([12.94, 79.14]);
  assert.ok(x1 > x0 && y1 < y0);                                    // east is right, north is up (smaller y)
  assert.ok(x0 >= 10 && y0 <= 310 && x1 <= 550 && y1 >= 10);       // inside the padding
  const dx = x1 - x0, dy = y0 - y1;
  assert.ok(Math.abs(dx / dy - Math.cos(12.92 * Math.PI / 180)) < 0.01);   // 0.04 degrees of both, east-west is shorter on the ground
  assert.equal(line.split(' ').length, 2);
  assert.equal(fitPath([], 10, 10).line, '');
});

test('matrix cells map to tones and times convert to the API format', () => {
  assert.equal(matrixTone('anomaly'), 'bad');
  assert.equal(matrixTone('prevented (error 40001)'), 'info');
  assert.equal(matrixTone('no anomaly'), 'ok');
  assert.equal(localToApi('2026-11-01T08:00'), '2026-11-01T08:00:00+05:30');
  assert.equal(localToApi('2026-11-01T08:00:30'), '2026-11-01T08:00:30+05:30');
  assert.equal(localToApi(''), '');
  assert.equal(daysBetween('2026-11-01', '2026-11-08'), 7);
});
