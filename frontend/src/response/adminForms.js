/**
 * Form helpers for administrator maintenance (FR-06 zones and units, FR-09 relief catalogue).
 * These only help the person fill the form in; PostgreSQL's constraints and trigger remain the authority.
 */
export const RISK_LEVELS = ['LOW', 'MEDIUM', 'HIGH'];
export const UNIT_TYPES = ['FIRE', 'MEDICAL', 'POLICE', 'RESCUE', 'RELIEF'];
export const CATEGORIES = ['FOOD', 'WATER', 'MEDICAL', 'SHELTER', 'EQUIPMENT'];
export const PHONE_PATTERN = /^[6-9][0-9]{9}$/;

const text = value => String(value ?? '').trim();
const whole = value => (value === '' || value === null || value === undefined ? null : Number(value));

export const blankZone = () => ({ zone_name: '', district: '', risk_level: 'MEDIUM' });
export const blankUnit = zoneId => ({ unit_name: '', unit_type: 'RESCUE', contact_phone: '', personnel_count: 4, zone_id: zoneId ?? '', lead_user_id: '' });
export const blankResource = () => ({ resource_name: '', category: 'FOOD', unit_of_measure: '', quantity_available: 0, reorder_level: 0 });

/** Problems a person can fix before sending (the database re-checks everything). */
export function problems(kind, form) {
  const found = [];
  if (kind === 'zone') {
    if (!text(form.zone_name)) found.push('Zone name is required.');
    if (!text(form.district)) found.push('District is required.');
    if (!RISK_LEVELS.includes(form.risk_level)) found.push('Risk level must be LOW, MEDIUM or HIGH.');
  } else if (kind === 'unit') {
    if (!text(form.unit_name)) found.push('Unit name is required.');
    if (!UNIT_TYPES.includes(form.unit_type)) found.push('Choose a unit type.');
    if (!PHONE_PATTERN.test(text(form.contact_phone))) found.push('Phone must be ten digits starting with 6, 7, 8 or 9.');
    if (!(Number(form.personnel_count) >= 1)) found.push('Personnel must be at least 1.');
    if (!form.zone_id) found.push('Choose the base zone.');
  } else if (kind === 'resource') {
    if (!text(form.resource_name)) found.push('Item name is required.');
    if (!CATEGORIES.includes(form.category)) found.push('Choose a category.');
    if (!text(form.unit_of_measure)) found.push('Unit of measure is required.');
    if (Number(form.quantity_available) < 0 || Number(form.reorder_level) < 0) found.push('Quantities cannot be negative.');
  }
  return found;
}

export function createBody(kind, form) {
  if (kind === 'zone') return { zone_name: text(form.zone_name), district: text(form.district), risk_level: form.risk_level };
  if (kind === 'unit') return { unit_name: text(form.unit_name), unit_type: form.unit_type, contact_phone: text(form.contact_phone), personnel_count: Number(form.personnel_count),
    zone_id: Number(form.zone_id), ...(form.lead_user_id ? { lead_user_id: Number(form.lead_user_id) } : {}) };
  return { resource_name: text(form.resource_name), category: form.category, unit_of_measure: text(form.unit_of_measure),
    quantity_available: Number(form.quantity_available) || 0, reorder_level: Number(form.reorder_level) || 0 };
}

/** Form values for an existing record (what the edit form starts with). */
export function formFrom(kind, record) {
  if (kind === 'zone') return { zone_name: record.zone_name, district: record.district, risk_level: record.risk_level };
  if (kind === 'unit') return { unit_name: record.unit_name, unit_type: record.unit_type, contact_phone: record.contact_phone ?? '', personnel_count: record.personnel_count ?? 1,
    zone_id: record.zone_id, lead_user_id: record.lead_user_id ?? '' };
  return { resource_name: record.resource_name, category: record.category, unit_of_measure: record.unit_of_measure, quantity_available: record.quantity_available, reorder_level: record.reorder_level };
}

/**
 * Only the fields that changed. A cleared lead is sent as an explicit null (the server treats a present key as
 * "set the lead"); a lead that did not change is not sent at all. Stock quantity is never part of an edit.
 */
export function changeBody(kind, original, form) {
  const before = formFrom(kind, original);
  const changed = {};
  const keys = kind === 'zone' ? ['zone_name', 'district', 'risk_level']
    : kind === 'unit' ? ['unit_name', 'contact_phone', 'personnel_count', 'zone_id', 'lead_user_id']
      : ['resource_name', 'category', 'unit_of_measure', 'reorder_level'];
  for (const key of keys) {
    const a = before[key] ?? '', b = form[key] ?? '';
    if (String(a).trim() === String(b).trim()) continue;
    changed[key] = key === 'lead_user_id' ? whole(b) : (['personnel_count', 'zone_id', 'reorder_level'].includes(key) ? Number(b) : text(b));
  }
  return changed;
}
