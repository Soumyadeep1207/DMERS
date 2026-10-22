import React, { useCallback, useEffect, useState } from 'react';
import { get, patch, post } from './api.js';
import { CATEGORIES, RISK_LEVELS, UNIT_TYPES, blankResource, blankUnit, blankZone, changeBody, createBody, formFrom, problems } from './adminForms.js';

const SECTIONS = [['zones', 'Zones', 'zone'], ['units', 'Response units', 'unit'], ['resources', 'Relief items', 'resource']];
const PATHS = { zone: 'zones', unit: 'units', resource: 'resources' };
const LABEL = { zone: 'zone', unit: 'response unit', resource: 'relief item' };

function Field({ label, children }) { return <label className="rs-field"><span>{label}</span>{children}</label>; }

/** FR-06 and FR-09: the administrator creates and edits zones, response units and relief items. */
export default function AdminPanel() {
  const [ref, setRef] = useState(null);
  const [section, setSection] = useState('zones');
  const [editing, setEditing] = useState(null);                 // the record being edited, or null for "new"
  const [form, setForm] = useState(null);
  const [notice, setNotice] = useState({ tone: '', text: 'Choose a record to edit, or add a new one.' });
  const [busy, setBusy] = useState(false);
  const kind = SECTIONS.find(s => s[0] === section)[2];

  const load = useCallback(async () => { const r = await get('/api/response/reference'); if (r.ok) setRef(r.body); }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!ref) return;
    setEditing(null);
    setForm(kind === 'zone' ? blankZone() : kind === 'unit' ? blankUnit(ref.zones[0]?.id) : blankResource());
  }, [section, ref === null]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!ref || !form) return <section className="dm-panel"><p className="dm-muted">Loading…</p></section>;
  const records = section === 'zones' ? ref.zones : section === 'units' ? ref.units : ref.resources;
  const set = (key, value) => setForm({ ...form, [key]: value });
  const title = record => (kind === 'zone' ? `${record.zone_name} · ${record.district}` : kind === 'unit' ? `${record.unit_name} · ${record.unit_type}` : `${record.resource_name} · ${record.category}`);
  const detail = record => (kind === 'zone' ? `risk ${record.risk_level}` : kind === 'unit' ? `${record.availability_status}${record.lead_name ? ` · lead ${record.lead_name}` : ' · no lead'}` : `${record.quantity_available} in stock · reorder at ${record.reorder_level}`);
  const issues = problems(kind, form);

  const choose = record => { setEditing(record); setForm(formFrom(kind, record)); setNotice({ tone: '', text: `Editing ${LABEL[kind]} #${record.id}.` }); };
  const fresh = () => { setEditing(null); setForm(kind === 'zone' ? blankZone() : kind === 'unit' ? blankUnit(ref.zones[0]?.id) : blankResource()); setNotice({ tone: '', text: `New ${LABEL[kind]}.` }); };

  const save = async event => {
    event.preventDefault();
    setBusy(true);
    const label = `${editing ? 'Edit' : 'Create'} ${LABEL[kind]}`;
    let result;
    if (editing) {
      const body = changeBody(kind, editing, form);
      if (!Object.keys(body).length) { setBusy(false); return setNotice({ tone: '', text: 'Nothing has changed.' }); }
      result = await patch(`/api/response/${PATHS[kind]}/${editing.id}`, body, { label, person: 'Administrator' });
    } else result = await post(`/api/response/${PATHS[kind]}`, createBody(kind, form), { label, person: 'Administrator' });
    setBusy(false);
    if (result.ok) { await load(); if (!editing) fresh(); setNotice({ tone: 'ok', text: `${label}: committed and recorded in the audit trail.` }); }   // message last: fresh() resets it
    else setNotice({ tone: 'bad', text: `${label}: refused. ${result.body.error}${result.body.constraint ? ` (${result.body.constraint})` : ''} Nothing was changed.` });
  };

  return <section className="dm-panel rs-admin">
    <div className="dm-panel-head"><p className="dm-eyebrow">Administration · FR-06 and FR-09</p><h2>Reference data</h2>
      <p className="dm-muted">Zones, response units and the relief catalogue. Each change is one database transaction, checked by the table constraints (and, for a unit's lead, by a trigger), and written to the audit trail. Stock quantities change only through restocking and allocation.</p></div>
    <div className="rs-tabs" role="tablist">{SECTIONS.map(([id, label]) => <button key={id} role="tab" aria-selected={section === id} className={section === id ? 'active' : ''} onClick={() => setSection(id)}>{label}</button>)}</div>
    <p className={`rs-notice ${notice.tone}`} role="status">{notice.text}</p>
    <div className="rs-layout admin">
      <div className="rs-form"><div className="dm-block-head"><h3>{editing ? `Edit ${LABEL[kind]} #${editing.id}` : `Add a ${LABEL[kind]}`}</h3>{editing && <button type="button" className="dm-btn small" onClick={fresh}>New instead</button>}</div>
        <form className="rs-form flat" onSubmit={save}>
          {kind === 'zone' && <>
            <Field label="Zone name"><input value={form.zone_name} onChange={e => set('zone_name', e.target.value)} maxLength="60" /></Field>
            <Field label="District"><input value={form.district} onChange={e => set('district', e.target.value)} maxLength="60" /></Field>
            <Field label="Risk level"><select value={form.risk_level} onChange={e => set('risk_level', e.target.value)}>{RISK_LEVELS.map(r => <option key={r}>{r}</option>)}</select></Field></>}
          {kind === 'unit' && <>
            <Field label="Unit name"><input value={form.unit_name} onChange={e => set('unit_name', e.target.value)} maxLength="60" /></Field>
            <Field label="Type"><select value={form.unit_type} disabled={Boolean(editing)} onChange={e => set('unit_type', e.target.value)}>{UNIT_TYPES.map(t => <option key={t}>{t}</option>)}</select></Field>
            <Field label="Contact phone"><input value={form.contact_phone} onChange={e => set('contact_phone', e.target.value)} placeholder="10 digits, starts 6-9" maxLength="10" /></Field>
            <Field label="Personnel"><input type="number" min="1" value={form.personnel_count} onChange={e => set('personnel_count', e.target.value)} /></Field>
            <Field label="Base zone"><select value={form.zone_id} onChange={e => set('zone_id', e.target.value)}>{ref.zones.map(z => <option key={z.id} value={z.id}>{z.zone_name}</option>)}</select></Field>
            <Field label="Lead (UNIT_LEAD accounts only)"><select value={form.lead_user_id} onChange={e => set('lead_user_id', e.target.value)}><option value="">No lead</option>
              {ref.lead_candidates.map(l => <option key={l.id} value={l.id}>{l.name}{l.leads_unit && l.leads_unit !== editing?.unit_name ? ` (already leads ${l.leads_unit})` : ''}</option>)}</select></Field></>}
          {kind === 'resource' && <>
            <Field label="Item name"><input value={form.resource_name} onChange={e => set('resource_name', e.target.value)} maxLength="60" /></Field>
            <Field label="Category"><select value={form.category} onChange={e => set('category', e.target.value)}>{CATEGORIES.map(c => <option key={c}>{c}</option>)}</select></Field>
            <Field label="Unit of measure"><input value={form.unit_of_measure} onChange={e => set('unit_of_measure', e.target.value)} maxLength="20" placeholder="packets, cans, kits…" /></Field>
            {!editing && <Field label="Opening stock"><input type="number" min="0" value={form.quantity_available} onChange={e => set('quantity_available', e.target.value)} /></Field>}
            <Field label="Reorder level"><input type="number" min="0" value={form.reorder_level} onChange={e => set('reorder_level', e.target.value)} /></Field></>}
          {issues.length > 0 && <ul className="rs-hints">{issues.map(i => <li key={i}>{i}</li>)}</ul>}
          <button className="dm-primary" disabled={busy}>{busy ? 'Saving…' : editing ? 'Save changes' : `Add ${LABEL[kind]}`}</button>
        </form>
        <p className="rs-muted">The hints above are only a convenience; the database makes the final decision and says why when it refuses.</p>
      </div>
      <ul className="rs-incidents">{records.map(r => <li key={r.id}><button className={editing?.id === r.id ? 'active' : ''} onClick={() => choose(r)}><span><b>{title(r)}</b></span><small>{detail(r)}</small></button></li>)}</ul>
    </div>
  </section>;
}
