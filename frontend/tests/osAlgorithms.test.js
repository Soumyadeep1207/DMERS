import test from 'node:test';
import assert from 'node:assert/strict';
import { scheduleTasks, bankerSafeSequence, evaluateBankerRequest } from '../src/osAlgorithms.js';

test('FCFS reports completion, turnaround, waiting and response times', () => {
  const result = scheduleTasks([{ id: 'P1', name: 'SOS', arrival: 0, burst: 5 }, { id: 'P2', name: 'Dispatch', arrival: 1, burst: 4 }], 'FCFS');
  assert.deepEqual(result.gantt.map(slot => [slot.id, slot.start, slot.end]), [['P1', 0, 5], ['P2', 5, 9]]);
  assert.deepEqual(result.rows.map(row => [row.completion, row.turnaround, row.waiting, row.response]), [[5, 5, 0, 0], [9, 8, 4, 4]]);
});

test('non-preemptive SJF chooses the shortest ready task', () => {
  const result = scheduleTasks([{ id: 'P1', arrival: 0, burst: 8 }, { id: 'P2', arrival: 1, burst: 2 }, { id: 'P3', arrival: 2, burst: 1 }], 'SJF');
  assert.deepEqual(result.gantt.map(slot => slot.id), ['P1', 'P3', 'P2']);
});

test('Round Robin honors its quantum and arrival order', () => {
  const result = scheduleTasks([{ id: 'P1', arrival: 0, burst: 5 }, { id: 'P2', arrival: 1, burst: 2 }], 'RR', 2);
  assert.deepEqual(result.gantt.map(slot => [slot.id, slot.start, slot.end]), [['P1', 0, 2], ['P2', 2, 4], ['P1', 4, 6], ['P1', 6, 7]]);
});

const available = [3, 3, 2];
const allocation = [[0,1,0],[2,0,0],[3,0,2],[2,1,1],[0,0,2]];
const maximum = [[7,5,3],[3,2,2],[9,0,2],[2,2,2],[4,3,3]];

test('Banker safe-state check finds the standard safe sequence', () => {
  assert.deepEqual(bankerSafeSequence(available, allocation, maximum).order, ['P1','P3','P4','P0','P2']);
});

test('Banker grants a safe request and refuses an unsafe request', () => {
  assert.equal(evaluateBankerRequest(available, allocation, maximum, 1, [1,0,2]).granted, true);
  const unsafe = evaluateBankerRequest(available, allocation, maximum, 4, [3,3,0]);
  assert.equal(unsafe.granted, false);
  assert.equal(unsafe.safe, false);
});
