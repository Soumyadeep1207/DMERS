import test from 'node:test';
import assert from 'node:assert/strict';
import { describeTrace, effectLines, rowSummary, pushActivity, FIVE_QUESTIONS } from '../src/response/trace.js';
import { toCsv, safeCell, layoutReport, columnWidths, clip } from '../src/response/reportExport.js';
import { STEPS, TRANSACTION_GROUPS, newContext, PERSONAS } from '../src/response/demoScript.js';

const successTrace = {
  operation: 'Dispatch a unit', outcome: 'committed', rolled_back: false, tables_touched: ['dispatches', 'response_units', 'incidents', 'incident_updates'],
  components: ['CALL sp_dispatch_unit', 'trigger trg_dispatches_guard', 'trigger trg_incidents_timeline'], rows_affected: 4,
  row_changes: { dispatches: { inserted: 1 }, response_units: { updated: 1 }, incidents: { updated: 1 }, incident_updates: { inserted: 1 } },
  effects: [{ label: 'Unit', before: { availability_status: 'AVAILABLE' }, after: { availability_status: 'DEPLOYED' } }],
  notices: ['Unit 2 dispatched'], statements: ['CALL sp_dispatch_unit(%s, %s, %s)'], statement_status: ['ok'], duration_ms: 15.8, constraints_checked: [], component_details: [],
};
const failedTrace = { ...successTrace, outcome: 'rolled_back', rolled_back: true, rows_affected: 0, row_changes: {}, notices: [], components: ['CALL sp_dispatch_unit', 'trigger trg_dispatches_guard'],
  effects: [{ label: 'Unit', before: { availability_status: 'DEPLOYED' }, after: { availability_status: 'DEPLOYED' }, unchanged: true }], failure: { constraint: null, message: 'Unit 9 is DEPLOYED, not AVAILABLE', sqlstate: 'P0001' } };

test('a committed trace answers the five guideline questions', () => {
  const d = describeTrace(successTrace);
  assert.equal(d.outcome, 'COMMITTED');
  assert.deepEqual(d.answers.map(a => a.question), FIVE_QUESTIONS);
  assert.deepEqual(d.answers[1].answer, successTrace.tables_touched);
  assert.ok(d.answers[2].answer.includes('trigger trg_dispatches_guard'));
  assert.ok(d.answers[3].answer[0].startsWith('4 rows changed') && d.answers[3].answer[1].includes('AVAILABLE') && d.answers[3].answer[1].includes('DEPLOYED'));
  assert.match(d.answers[4].answer[0], /Committed in 15.8 ms.*Unit 2 dispatched/);
});

test('a rolled-back trace says nothing changed and names the refusal', () => {
  const d = describeTrace(failedTrace, 'Unit 9 is DEPLOYED, not AVAILABLE');
  assert.equal(d.outcome, 'ROLLED BACK');
  assert.match(d.answers[3].answer[0], /rolled back/);
  assert.match(d.answers[3].answer[1], /unchanged/);
  assert.match(d.answers[4].answer[0], /Refused by the database: Unit 9 is DEPLOYED/);
  assert.equal(describeTrace(null), null);
});

test('row and effect summaries are readable', () => {
  assert.deepEqual(rowSummary({ incidents: { inserted: 1, updated: 2 } }), ['incidents: 1 inserted, 2 updated']);
  assert.deepEqual(effectLines([{ label: 'Stock', before: { qty: 350 }, after: { qty: 320 } }]), ['Stock: qty 350 → qty 320']);
  assert.deepEqual(effectLines([{ label: 'Allocation', before: null, after: { quantity: 30 } }]), ['Allocation: none → quantity 30']);
});

test('the activity list is newest first and bounded', () => {
  let list = [];
  for (let i = 0; i < 40; i += 1) list = pushActivity(list, { id: i });
  assert.equal(list.length, 30);
  assert.equal(list[0].id, 39);
});

const report = { key: 'stock-status', title: 'Relief stock status', requirement: 'FR-13', review2_query: 'Q5', sql_feature: 'fn_stock_status', time_zone: 'Asia/Kolkata',
  parameters: { only_low: true }, columns: ['resource_name', 'available', 'stock_status'],
  rows: [['Inflatable rescue boats', 0, 'OUT_OF_STOCK'], ['=cmd|calc', 3, 'LOW']] };

test('CSV carries metadata, quotes cells and neutralises spreadsheet formulas', () => {
  const csv = toCsv(report);
  assert.ok(csv.startsWith('﻿"Relief stock status"'));
  assert.ok(csv.includes('"Requirement","FR-13","Review II query","Q5"'));
  assert.ok(csv.includes('"\'=cmd|calc"'));
  assert.equal(safeCell(null), '');
  assert.equal(safeCell('-5'), "'-5");
  assert.equal(safeCell('plain'), 'plain');
});

test('PDF layout paginates, repeats the header and truncates long text', () => {
  const rows = Array.from({ length: 75 }, (_, i) => [`Item ${i}`, i, 'ADEQUATE'.repeat(10)]);
  const layout = layoutReport({ ...report, rows }, { rowsFirstPage: 28, rowsPerPage: 40, generatedAt: new Date('2026-10-22T10:00:00Z') });
  assert.equal(layout.pages.length, 3);
  assert.deepEqual(layout.pages.map(p => p.rows.length), [28, 40, 7]);
  assert.equal(layout.meta.length, 4);
  assert.ok(layout.meta[3].includes('only_low=true'));
  assert.ok(layout.pages[0].rows[0][2].endsWith('…'));
  assert.equal(layoutReport({ ...report, rows: [] }).pages.length, 1);          // an empty report still prints
  assert.equal(clip('abcdef', 4), 'abc…');
  assert.ok(columnWidths(['a', 'b'], [['x'.repeat(30), 'y']]).every(w => w >= 4));
});

test('the demo covers T1-T10, names who acts, and flags every refusal with its status', () => {
  const groups = new Set(STEPS.map(s => s.group));
  for (const g of TRANSACTION_GROUPS) assert.ok(groups.has(g), `missing ${g}`);
  const persons = new Set(Object.keys(PERSONAS));
  for (const s of STEPS) {
    assert.ok(s.title && s.why && typeof s.request === 'function', s.id);
    assert.ok(s.person === null || persons.has(s.person), `${s.id} person`);
    assert.equal(Boolean(s.failure), s.expect >= 400, `${s.id}: failure flag must match the expected status`);
  }
  assert.equal(new Set(STEPS.map(s => s.id)).size, STEPS.length);
  assert.ok(STEPS.filter(s => s.failure).length >= 8, 'the failure cases must be shown');
});

test('the demo context resolves names and fails clearly when data is missing', () => {
  const refs = { units: [{ id: 2, unit_name: 'Katpadi Fire Unit' }], resources: [{ id: 7, resource_name: 'Blankets' }], zones: [{ id: 1, zone_name: 'Vellore Town' }] };
  const ctx = newContext(refs, 123);
  assert.equal(ctx.email, 'demo.citizen.123@example.org');
  assert.equal(ctx.unit('Katpadi Fire Unit'), 2);
  assert.throws(() => ctx.unit('Nope'), /Reset/);
  const [method, path, body] = STEPS.find(s => s.id === 't3-verify').request({ ...ctx, incident: 15 });
  assert.equal(method, 'POST');
  assert.equal(path, '/api/response/incidents/15/verify');
  assert.equal(body.zone_id, 1);
});
