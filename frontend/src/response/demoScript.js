/**
 * The guided demonstration: transactions T1-T10 in order, each with the person who performs it and
 * whether the database is expected to accept or refuse it. Pure data plus small builders so it can be
 * tested; the screen and the headless script (scripts/demo_transactions.py) follow the same plan.
 *
 * ``ctx`` collects ids as the walk-through proceeds (the incident just reported, unit ids, ...).
 */
export const PERSONAS = {
  citizen: 'Gopal Iyer',
  coordinator: 'Priya Natarajan',
  lead: 'Divya Ramesh',
  admin: 'Meena Krishnan',
};

const R = '/api/response';

export const STEPS = [
  { id: 't1-register', group: 'T1', title: 'Register a new citizen', person: null, expect: 201, why: 'INSERT into users: UNIQUE e-mail, derived account_type, password stored only as a hash.',
    request: ctx => ['POST', '/api/auth/register', { name: 'Demo Citizen', email: ctx.email, password: 'Demo@12345', role: 'citizen' }] },
  { id: 't1-duplicate', group: 'T1', title: 'Register the same e-mail again', person: null, expect: 409, failure: true, why: 'The UNIQUE constraint on e-mail rejects the row and the transaction rolls back.',
    request: ctx => ['POST', '/api/auth/register', { name: 'Demo Citizen', email: ctx.email, password: 'Demo@12345' }] },
  { id: 't2-report', group: 'T2', title: 'Citizen reports a fire', person: 'citizen', expect: 201, why: 'INSERT into incidents: defaults give REPORTED / MODERATE and trigger T1 writes timeline entry 1.',
    request: () => ['POST', `${R}/incidents`, { title: 'Smoke from a warehouse near the Fort', incident_type: 'FIRE', location: 'Fort Round Road, Vellore', description: 'Heavy smoke, people outside' }],
    after: (ctx, body) => { ctx.incident = body.incident.id; } },
  { id: 't3-forbidden', group: 'T3', title: 'A citizen tries to verify', person: 'citizen', expect: 403, failure: true, why: 'Only coordinators verify: the server checks the account type from the database.',
    request: ctx => ['POST', `${R}/incidents/${ctx.incident}/verify`, { zone_id: ctx.zone('Vellore Town'), severity: 'HIGH' }] },
  { id: 't4-early', group: 'T3', title: 'Dispatch before verification', person: 'coordinator', expect: 422, failure: true, why: 'Guard trigger T3 refuses an incident that is not VERIFIED or RESPONDING.',
    request: ctx => ['POST', `${R}/incidents/${ctx.incident}/dispatch`, { unit_id: ctx.unit('Katpadi Fire Unit') }] },
  { id: 't3-verify', group: 'T3', title: 'Coordinator verifies: Vellore Town, HIGH', person: 'coordinator', expect: 200, why: 'UPDATE incidents passes ck_incidents_zone_when_verified; triggers T2 and T1 stamp the time and the author.',
    request: ctx => ['POST', `${R}/incidents/${ctx.incident}/verify`, { zone_id: ctx.zone('Vellore Town'), severity: 'HIGH', note: 'Confirmed by caller and photos' }] },
  { id: 't4-busy', group: 'T4', title: 'Dispatch SDRF Team Alpha (already deployed)', person: 'coordinator', expect: 422, failure: true, why: 'sp_dispatch_unit inserts a dispatch; guard trigger T3 locks the unit and refuses it (BR-05).',
    request: ctx => ['POST', `${R}/incidents/${ctx.incident}/dispatch`, { unit_id: ctx.unit('SDRF Team Alpha') }] },
  { id: 't4-dispatch', group: 'T4', title: 'Dispatch Katpadi Fire Unit', person: 'coordinator', expect: 201, why: 'CALL sp_dispatch_unit: guard trigger, unit becomes DEPLOYED, incident becomes RESPONDING, a NOTICE is returned.',
    request: ctx => ['POST', `${R}/incidents/${ctx.incident}/dispatch`, { unit_id: ctx.unit('Katpadi Fire Unit') }] },
  { id: 't5-notlead', group: 'T5', title: 'A citizen tries to move the dispatch', person: 'citizen', expect: 422, failure: true, why: 'sp_update_dispatch accepts only the lead of the unit.',
    request: ctx => ['PATCH', `${R}/dispatches/${ctx.incident}/${ctx.unit('Katpadi Fire Unit')}`, { status: 'EN_ROUTE' }] },
  { id: 't5-enroute', group: 'T5', title: 'Unit lead: EN_ROUTE', person: 'lead', expect: 200, why: 'CALL sp_update_dispatch: ASSIGNED to EN_ROUTE.',
    request: ctx => ['PATCH', `${R}/dispatches/${ctx.incident}/${ctx.unit('Katpadi Fire Unit')}`, { status: 'EN_ROUTE' }] },
  { id: 't5-skip', group: 'T5', title: 'Unit lead jumps to COMPLETED', person: 'lead', expect: 422, failure: true, why: 'Illegal order: the procedure refuses and everything rolls back.',
    request: ctx => ['PATCH', `${R}/dispatches/${ctx.incident}/${ctx.unit('Katpadi Fire Unit')}`, { status: 'COMPLETED' }] },
  { id: 't5-onscene', group: 'T5', title: 'Unit lead: ON_SCENE', person: 'lead', expect: 200, why: 'Arrival time recorded; CHECK ck_dispatches_arrival (BR-06) holds.',
    request: ctx => ['PATCH', `${R}/dispatches/${ctx.incident}/${ctx.unit('Katpadi Fire Unit')}`, { status: 'ON_SCENE' }] },
  { id: 't6-a', group: 'T6', title: 'Allocate 30 blankets', person: 'coordinator', expect: 201, why: 'INSERT ... ON CONFLICT DO UPDATE; AFTER trigger T4 moves stock and adds a timeline note.',
    request: ctx => ['POST', `${R}/incidents/${ctx.incident}/allocations`, { resource_id: ctx.resource('Blankets'), quantity: 30 }] },
  { id: 't6-b', group: 'T6', title: 'Allocate 20 more (cumulative)', person: 'coordinator', expect: 201, why: 'The conflict path adds to the existing allocation: quantity becomes 50.',
    request: ctx => ['POST', `${R}/incidents/${ctx.incident}/allocations`, { resource_id: ctx.resource('Blankets'), quantity: 20 }] },
  { id: 't6-boat', group: 'T6', title: 'Allocate an inflatable boat (none in stock)', person: 'coordinator', expect: 422, failure: true, why: 'Trigger T4 refuses over-allocation; the allocation row and the stock change roll back.',
    request: ctx => ['POST', `${R}/incidents/${ctx.incident}/allocations`, { resource_id: ctx.resource('Inflatable rescue boats'), quantity: 1 }] },
  { id: 't9-withdraw', group: 'T9', title: 'Withdraw the blanket allocation', person: 'coordinator', expect: 200, why: 'DELETE fires trigger T4 again: the stock returns and a timeline note is added.',
    request: ctx => ['DELETE', `${R}/incidents/${ctx.incident}/allocations/${ctx.resource('Blankets')}`, null] },
  { id: 't7-close', group: 'T7', title: 'Close the incident', person: 'coordinator', expect: 200, why: 'CALL sp_close_incident: an explicit cursor releases each active unit (one NOTICE each), then RESOLVED and CLOSED.',
    request: ctx => ['POST', `${R}/incidents/${ctx.incident}/close`, { note: 'Fire out, area made safe' }] },
  { id: 't8-forbidden', group: 'T8', title: 'A coordinator tries to restock', person: 'coordinator', expect: 403, failure: true, why: 'Restocking is an administrator action, checked on the server.',
    request: ctx => ['POST', `${R}/resources/${ctx.resource('Inflatable rescue boats')}/restock`, { quantity: 3 }] },
  { id: 't8-restock', group: 'T8', title: 'Administrator adds 3 inflatable boats', person: 'admin', expect: 200, why: 'UPDATE resources, then fn_stock_status read in a separate SELECT: OUT_OF_STOCK becomes LOW.',
    request: ctx => ['POST', `${R}/resources/${ctx.resource('Inflatable rescue boats')}/restock`, { quantity: 3 }] },
  { id: 't8-negative', group: 'T8', title: 'Remove more boats than exist', person: 'admin', expect: 422, failure: true, why: 'CHECK ck_resources_quantity refuses a negative stock.',
    request: ctx => ['POST', `${R}/resources/${ctx.resource('Inflatable rescue boats')}/restock`, { quantity: -50 }] },
  { id: 't9-dup', group: 'T9', title: 'Citizen files a duplicate report', person: 'citizen', expect: 201, why: 'A second INSERT; trigger T1 writes its first timeline entry.',
    request: () => ['POST', `${R}/incidents`, { title: 'Same fire, second report', incident_type: 'FIRE', location: 'Fort Round Road, Vellore' }],
    after: (ctx, body) => { ctx.duplicate = body.incident.id; } },
  { id: 't9-reject', group: 'T9', title: 'Coordinator rejects it as a duplicate', person: 'coordinator', expect: 200, why: 'UPDATE status to REJECTED; the transition guard allows it and the timeline records the note.',
    request: ctx => ['POST', `${R}/incidents/${ctx.duplicate}/reject`, { note: `Duplicate of incident ${ctx.incident}` }] },
  { id: 't9-delete', group: 'T9', title: 'Delete the rejected duplicate', person: 'coordinator', expect: 200, why: 'DELETE; ON DELETE CASCADE removes its timeline (trigger T5 allows a cascade).',
    request: ctx => ['DELETE', `${R}/incidents/${ctx.duplicate}`, null] },
  { id: 't9-restrict', group: 'T9', title: 'Delete an incident that has dispatch history', person: 'coordinator', expect: 409, failure: true, why: 'ON DELETE RESTRICT on dispatches protects history: HTTP 409.',
    request: ctx => ['DELETE', `${R}/incidents/${ctx.incident}`, null] },
  { id: 't10-append', group: 'T10', title: 'Try to rewrite timeline entry 1', person: 'admin', expect: 422, failure: true, why: 'Trigger T5 makes the timeline append-only, even for administrators.',
    request: ctx => ['POST', `${R}/debug/edit-timeline`, { incident_id: ctx.incident, update_no: 1, note: 'tampered' }] },
  { id: 't11-zone', group: 'T11', title: 'Administrator adds a zone', person: 'admin', expect: 201, why: 'FR-06: INSERT into zones (CHECK on risk level, UNIQUE name) and an audit entry, in one transaction.',
    request: ctx => ['POST', `${R}/zones`, { zone_name: ctx.zoneName, district: 'Vellore', risk_level: 'MEDIUM' }],
    after: (ctx, body) => { ctx.newZone = body.zone.id; } },
  { id: 't11-zone-dup', group: 'T11', title: 'Add the same zone again', person: 'admin', expect: 409, failure: true, why: 'UNIQUE uq_zones_name refuses it; the audit entry rolls back with it.',
    request: ctx => ['POST', `${R}/zones`, { zone_name: ctx.zoneName, district: 'Vellore', risk_level: 'LOW' }] },
  { id: 't11-unit', group: 'T11', title: 'Administrator adds a response unit in the new zone', person: 'admin', expect: 201, why: 'FR-06: INSERT into response_units (phone CHECK, personnel CHECK, zone foreign key); availability takes its DEFAULT.',
    request: ctx => ['POST', `${R}/units`, { unit_name: ctx.unitName, unit_type: 'RESCUE', contact_phone: '9000088888', personnel_count: 5, zone_id: ctx.newZone }],
    after: (ctx, body) => { ctx.newUnit = body.unit.id; } },
  { id: 't11-lead-citizen', group: 'T11', title: 'Make a citizen the unit lead', person: 'admin', expect: 422, failure: true, why: 'Trigger trg_units_lead_type: only a UNIT_LEAD account may lead a unit.',
    request: ctx => ['PATCH', `${R}/units/${ctx.newUnit}`, { lead_user_id: ctx.userId('Gopal Iyer') }] },
  { id: 't11-lead-taken', group: 'T11', title: 'Give the unit a lead who already leads another', person: 'admin', expect: 409, failure: true, why: 'UNIQUE uq_units_lead: an account leads at most one unit.',
    request: ctx => ['PATCH', `${R}/units/${ctx.newUnit}`, { lead_user_id: ctx.userId('Divya Ramesh') }] },
  { id: 't11-resource', group: 'T11', title: 'Administrator adds a relief item', person: 'admin', expect: 201, why: 'FR-09: INSERT into resources; fn_stock_status reports LOW because 5 is below the reorder level of 10.',
    request: ctx => ['POST', `${R}/resources`, { resource_name: ctx.resourceName, category: 'WATER', unit_of_measure: 'cans', quantity_available: 5, reorder_level: 10 }] },
  { id: 't11-resource-neg', group: 'T11', title: 'Add an item with negative opening stock', person: 'admin', expect: 422, failure: true, why: 'CHECK ck_resources_quantity refuses it.',
    request: ctx => ['POST', `${R}/resources`, { resource_name: `${ctx.resourceName} B`, category: 'FOOD', unit_of_measure: 'packets', quantity_available: -5 }] },
];

export const TRANSACTION_GROUPS = ['T1', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'T8', 'T9', 'T10', 'T11'];

export function newContext(refs, stamp = Date.now(), people = []) {
  const byName = (items, key) => Object.fromEntries(items.map(i => [i[key], i.id]));
  const units = byName(refs.units, 'unit_name'), resources = byName(refs.resources, 'resource_name'), zones = byName(refs.zones, 'zone_name');
  const need = (map, name) => { if (!(name in map)) throw new Error(`Demonstration data is missing "${name}". Use Reset to reload it.`); return map[name]; };
  const users = Object.fromEntries(people.map(p => [p.name, p.id]));
  return { email: `demo.citizen.${stamp}@example.org`, zoneName: `Demo Zone ${stamp}`, unitName: `Demo Unit ${stamp}`, resourceName: `Demo item ${stamp}`,
    unit: n => need(units, n), resource: n => need(resources, n), zone: n => need(zones, n), userId: n => need(users, n) };
}
