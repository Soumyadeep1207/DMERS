import test from 'node:test';
import assert from 'node:assert/strict';
import { problems, createBody, changeBody, formFrom, blankUnit, blankZone, blankResource, PHONE_PATTERN, RISK_LEVELS } from '../src/response/adminForms.js';
import { STEPS, newContext } from '../src/response/demoScript.js';

test('zone, unit and resource forms report fixable problems', () => {
  assert.deepEqual(problems('zone', blankZone()), ['Zone name is required.', 'District is required.']);
  assert.deepEqual(problems('zone', { zone_name: 'A', district: 'B', risk_level: 'SEVERE' }), ['Risk level must be LOW, MEDIUM or HIGH.']);
  assert.equal(problems('zone', { zone_name: 'A', district: 'B', risk_level: 'HIGH' }).length, 0);
  const unit = { ...blankUnit(1), unit_name: 'U', contact_phone: '12345' };
  assert.ok(problems('unit', unit).includes('Phone must be ten digits starting with 6, 7, 8 or 9.'));
  assert.equal(problems('unit', { ...unit, contact_phone: '9000012345' }).length, 0);
  assert.ok(problems('unit', { ...unit, contact_phone: '9000012345', zone_id: '' }).includes('Choose the base zone.'));
  assert.ok(problems('resource', { ...blankResource(), resource_name: 'X', unit_of_measure: 'kits', quantity_available: -1 }).includes('Quantities cannot be negative.'));
  assert.ok(PHONE_PATTERN.test('6000000000') && !PHONE_PATTERN.test('5000000000') && !PHONE_PATTERN.test('900001234'));
  assert.deepEqual(RISK_LEVELS, ['LOW', 'MEDIUM', 'HIGH']);
});

test('create bodies are trimmed, numeric, and omit an empty lead', () => {
  assert.deepEqual(createBody('zone', { zone_name: ' Katpadi North ', district: 'Vellore ', risk_level: 'HIGH' }), { zone_name: 'Katpadi North', district: 'Vellore', risk_level: 'HIGH' });
  const unit = createBody('unit', { unit_name: 'U ', unit_type: 'FIRE', contact_phone: '9000012345', personnel_count: '6', zone_id: '2', lead_user_id: '' });
  assert.deepEqual(unit, { unit_name: 'U', unit_type: 'FIRE', contact_phone: '9000012345', personnel_count: 6, zone_id: 2 });
  assert.equal(createBody('unit', { ...unit, lead_user_id: '9' }).lead_user_id, 9);
  assert.deepEqual(createBody('resource', { resource_name: 'Buoys', category: 'EQUIPMENT', unit_of_measure: 'pcs', quantity_available: '8', reorder_level: '' }),
    { resource_name: 'Buoys', category: 'EQUIPMENT', unit_of_measure: 'pcs', quantity_available: 8, reorder_level: 0 });
});

test('an edit sends only what changed, and a cleared lead is an explicit null', () => {
  const unit = { id: 2, unit_name: 'Katpadi Fire Unit', unit_type: 'FIRE', contact_phone: '9000010102', personnel_count: 8, zone_id: 2, lead_user_id: 8 };
  const form = formFrom('unit', unit);
  assert.deepEqual(changeBody('unit', unit, form), {});
  assert.deepEqual(changeBody('unit', unit, { ...form, personnel_count: '9' }), { personnel_count: 9 });
  assert.deepEqual(changeBody('unit', unit, { ...form, lead_user_id: '' }), { lead_user_id: null });
  assert.deepEqual(changeBody('unit', unit, { ...form, lead_user_id: '11', zone_id: '3' }), { zone_id: 3, lead_user_id: 11 });
  const withoutLead = { ...unit, lead_user_id: null };
  assert.deepEqual(changeBody('unit', withoutLead, formFrom('unit', withoutLead)), {});          // null and '' are the same
  const item = { id: 7, resource_name: 'Blankets', category: 'SHELTER', unit_of_measure: 'pieces', quantity_available: 350, reorder_level: 150 };
  assert.deepEqual(changeBody('resource', item, { ...formFrom('resource', item), quantity_available: 999, reorder_level: '120' }), { reorder_level: 120 });   // stock is never edited here
});

test('the T11 demo steps use names from the context and flag every refusal', () => {
  const refs = { units: [], resources: [], zones: [] };
  const ctx = newContext(refs, 77, [{ id: 17, name: 'Gopal Iyer' }, { id: 9, name: 'Divya Ramesh' }]);
  assert.equal(ctx.zoneName, 'Demo Zone 77');
  assert.equal(ctx.userId('Divya Ramesh'), 9);
  assert.throws(() => ctx.userId('Nobody'), /Reset/);
  const t11 = STEPS.filter(s => s.group === 'T11');
  assert.equal(t11.length, 7);
  assert.ok(t11.every(s => s.person === 'admin'));
  assert.deepEqual(t11.filter(s => s.failure).map(s => s.expect), [409, 422, 409, 422]);
  const full = { ...ctx, newUnit: 5, newZone: 3 };
  assert.deepEqual(t11.find(s => s.id === 't11-lead-citizen').request(full), ['PATCH', '/api/response/units/5', { lead_user_id: 17 }]);
  assert.equal(t11.find(s => s.id === 't11-unit').request(full)[2].zone_id, 3);
});
