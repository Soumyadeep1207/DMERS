import React, { useCallback, useEffect, useRef, useState } from 'react';
import { del, get, patch, post } from './api.js';
import { connectLive } from './lab/live.js';

const SEVERITY_ORDER = ['CRITICAL', 'HIGH', 'MODERATE', 'LOW'];
const when = value => (value ? new Date(value).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '—');
const Chip = ({ children, tone = '' }) => <span className={`rs-chip ${tone}`}>{children}</span>;
const statusTone = status => ({ VERIFIED: 'info', RESPONDING: 'warn', RESOLVED: 'ok', CLOSED: 'muted', REJECTED: 'muted' }[status] || '');
const severityTone = severity => (severity === 'CRITICAL' ? 'bad' : severity === 'HIGH' ? 'warn' : '');

function Field({ label, children }) { return <label className="rs-field"><span>{label}</span>{children}</label>; }

export default function ResponseOps() {
  const [ref, setRef] = useState(null);
  const [incidents, setIncidents] = useState([]);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [filter, setFilter] = useState('');
  const [notice, setNotice] = useState({ tone: '', text: 'Choose an incident, or report a new one.' });
  const [busy, setBusy] = useState(false);
  const [unavailable, setUnavailable] = useState('');
  const me = ref?.me;
  const type = me?.account_type;
  const isCoordinator = type === 'COORDINATOR';

  const loadList = useCallback(async () => {
    const result = await get(`/api/response/incidents${filter ? `?status=${filter}` : ''}`);
    if (result.status === 501) return setUnavailable(result.body.error);
    if (result.ok) setIncidents(result.body.incidents);
  }, [filter]);
  const loadDetail = useCallback(async id => {
    if (!id) return setDetail(null);
    const result = await get(`/api/response/incidents/${id}`);
    setDetail(result.ok ? result.body : null);
  }, []);
  const loadRef = useCallback(async () => { const result = await get('/api/response/reference'); if (result.ok) setRef(result.body); else if (result.status === 501) setUnavailable(result.body.error); }, []);

  useEffect(() => { loadRef(); }, [loadRef]);
  useEffect(() => { loadList(); }, [loadList]);
  useEffect(() => { loadDetail(selected); }, [selected, loadDetail]);

  // LISTEN/NOTIFY push (database lab 7): PostgreSQL tells this screen when a change commits, so nothing polls.
  const latest = useRef({});
  latest.current = { loadList, loadDetail, selected };
  const [live, setLive] = useState('off');
  useEffect(() => {
    if (!type || type === 'CITIZEN') return undefined;
    let timer;
    const stop = connectLive(() => { clearTimeout(timer); timer = setTimeout(() => { latest.current.loadList(); if (latest.current.selected) latest.current.loadDetail(latest.current.selected); }, 250); }, setLive);
    return () => { clearTimeout(timer); stop(); };
  }, [type]);

  /** Run one transaction, show the database's own message on refusal, refresh what changed. */
  const act = async (label, run, after) => {
    setBusy(true);
    const result = await run();
    setBusy(false);
    if (result.ok) {
      const next = after ? after(result.body) : selected;      // a callback may return null (e.g. the incident was deleted)
      setNotice({ tone: 'ok', text: `${label}: committed.` });
      setSelected(next);
      await Promise.all([loadList(), loadRef(), loadDetail(next)]);
    }
    else setNotice({ tone: 'bad', text: `${label}: refused. ${result.body.error || 'Something went wrong.'}${result.body.constraint ? ` (${result.body.constraint})` : ''} Nothing was changed.` });
    return result;
  };

  if (unavailable) return <section className="dm-panel"><h2>Response operations</h2><p className="dm-callout warn">{unavailable}</p></section>;
  if (!ref) return <section className="dm-panel"><p className="dm-muted">Loading the incident-response model…</p></section>;

  const incident = detail?.incident;
  const open = incident && ['VERIFIED', 'RESPONDING'].includes(incident.status);
  const availableUnits = ref.units.filter(u => u.availability_status === 'AVAILABLE');
  const myUnitIds = new Set(ref.units.filter(u => u.lead_user_id === me.id).map(u => u.id));

  return <div className="rs-layout">
    <aside className="dm-panel rs-list">
      <div className="dm-panel-head"><p className="dm-eyebrow">Incident response{live === 'live' && <span className="rs-chip ok" title="PostgreSQL pushes changes (LISTEN/NOTIFY); this list does not poll" style={{ marginLeft: 8 }}>live</span>}</p><h2>Incidents</h2>
        <p className="dm-muted">Signed in as <b>{me.name}</b> · {type.replace('_', ' ').toLowerCase()}</p></div>
      <ReportForm types={ref.incident_types} busy={busy} onSubmit={body => act('Report an incident', () => post('/api/response/incidents', body, { person: me.name }), b => b.incident.id)} />
      <div className="dm-row"><label className="rs-field grow"><span>Filter</span><select value={filter} onChange={e => setFilter(e.target.value)}>
        <option value="">All incidents</option>{['REPORTED', 'VERIFIED', 'RESPONDING', 'RESOLVED', 'CLOSED', 'REJECTED'].map(s => <option key={s}>{s}</option>)}</select></label></div>
      <ul className="rs-incidents">{incidents.map(item => <li key={item.id}><button className={selected === item.id ? 'active' : ''} onClick={() => setSelected(item.id)}>
        <span><b>#{item.id}</b> {item.title}</span>
        <small><Chip tone={statusTone(item.status)}>{item.status}</Chip> <Chip tone={severityTone(item.severity)}>{item.severity}</Chip> {item.zone_name || 'no zone yet'}</small></button></li>)}
        {!incidents.length && <li className="rs-muted">No incidents to show.</li>}</ul>
    </aside>

    <section className="rs-detail">
      <p className={`rs-notice ${notice.tone}`} role="status">{notice.text}</p>
      {!incident && <div className="dm-empty"><b>Nothing selected</b><p>Pick an incident on the left. Each action you take runs as one database transaction and is explained in the Database activity drawer.</p></div>}
      {incident && <>
        <div className="dm-panel">
          <div className="dm-block-head"><div><p className="dm-eyebrow">Incident #{incident.id} · {incident.incident_type.replaceAll('_', ' ')}</p><h2>{incident.title}</h2></div>
            <div><Chip tone={statusTone(incident.status)}>{incident.status}</Chip> <Chip tone={severityTone(incident.severity)}>{incident.severity}</Chip></div></div>
          <p className="dm-muted">{incident.location} · zone {incident.zone_name || 'not assigned yet'} · reported by {incident.reporter} on {when(incident.created_at)}</p>
          {incident.description && <p>{incident.description}</p>}
          {isCoordinator && <Actions incident={incident} ref_={ref} open={open} availableUnits={availableUnits} busy={busy} act={act} setSelected={setSelected} />}
        </div>

        <div className="rs-grid">
          <div className="dm-panel"><h3>Dispatched units</h3>
            {detail.dispatches.length ? <ul className="rs-rows">{detail.dispatches.map(d => <li key={d.unit_id}>
              <span><b>{d.unit_name}</b> <small>{d.unit_type}</small><br /><small>dispatched by {d.dispatched_by} · {when(d.dispatched_at)}{d.arrived_at ? ` · arrived ${when(d.arrived_at)}` : ''}{d.cleared_at ? ` · cleared ${when(d.cleared_at)}` : ''}</small></span>
              <span className="rs-end"><Chip tone={d.dispatch_status === 'COMPLETED' ? 'ok' : d.dispatch_status === 'CANCELLED' ? 'muted' : 'warn'}>{d.dispatch_status}</Chip>
                {myUnitIds.has(d.unit_id) && nextStep(d.dispatch_status) && <button className="dm-btn small" disabled={busy}
                  onClick={() => act(`Unit progress (${nextStep(d.dispatch_status)})`, () => patch(`/api/response/dispatches/${incident.id}/${d.unit_id}`, { status: nextStep(d.dispatch_status) }, { person: me.name }))}>Mark {nextStep(d.dispatch_status).replace('_', ' ').toLowerCase()}</button>}</span></li>)}</ul>
              : <p className="dm-muted">No unit has been dispatched.</p>}</div>

          <div className="dm-panel"><h3>Relief allocated</h3>
            {detail.allocations.length ? <ul className="rs-rows">{detail.allocations.map(a => <li key={a.resource_id}><span><b>{a.resource_name}</b><br /><small>{a.quantity} {a.unit_of_measure} · {when(a.allocated_at)}</small></span>
              {isCoordinator && <button className="dm-btn small" disabled={busy} onClick={() => act('Withdraw an allocation', () => del(`/api/response/incidents/${incident.id}/allocations/${a.resource_id}`, { person: me.name }))}>Withdraw</button>}</li>)}</ul>
              : <p className="dm-muted">No relief allocated.</p>}</div>
        </div>

        <div className="dm-panel"><h3>Timeline <small className="rs-muted">append-only, written by trigger T1</small></h3>
          <ol className="rs-timeline">{detail.timeline.map(t => <li key={t.update_no}><b>{t.update_no}</b><span>{t.previous_status ? `${t.previous_status} → ` : ''}<b>{t.new_status}</b> — {t.note}<br /><small>{t.logged_by || 'system'} · {when(t.logged_at)}</small></span></li>)}</ol></div>
      </>}

      {type === 'ADMINISTRATOR' && <Restock resources={ref.resources} busy={busy} act={(label, run) => act(label, run)} person={me.name} />}
      <div className="dm-panel"><h3>Zones and relief stock</h3>
        <div className="rs-grid"><ul className="rs-rows compact">{ref.zones.map(z => <li key={z.id}><span>{z.zone_name} <small>{z.district}</small></span><span><Chip tone={z.risk_level === 'HIGH' ? 'warn' : ''}>{z.risk_level}</Chip> {z.active_incidents} active</span></li>)}</ul>
          <ul className="rs-rows compact">{ref.resources.map(r => <li key={r.id}><span>{r.resource_name}</span><span>{r.quantity_available} <Chip tone={r.stock_status === 'ADEQUATE' ? 'ok' : 'bad'}>{r.stock_status}</Chip></span></li>)}</ul></div></div>
    </section>
  </div>;
}

const nextStep = status => ({ ASSIGNED: 'EN_ROUTE', EN_ROUTE: 'ON_SCENE', ON_SCENE: 'COMPLETED' }[status]);

function ReportForm({ types, busy, onSubmit }) {
  const [form, setForm] = useState({ title: '', incident_type: 'FIRE', location: '', description: '' });
  const submit = async event => { event.preventDefault(); const r = await onSubmit(form); if (r?.ok) setForm({ title: '', incident_type: form.incident_type, location: '', description: '' }); };
  return <form className="rs-form" onSubmit={submit}><h3>Report an incident</h3>
    <Field label="Title"><input required maxLength="120" value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} placeholder="What happened?" /></Field>
    <Field label="Type"><select value={form.incident_type} onChange={e => setForm({ ...form, incident_type: e.target.value })}>{types.map(t => <option key={t}>{t}</option>)}</select></Field>
    <Field label="Location"><input required maxLength="150" value={form.location} onChange={e => setForm({ ...form, location: e.target.value })} placeholder="Street or landmark" /></Field>
    <Field label="Details (optional)"><textarea rows="2" maxLength="2000" value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} /></Field>
    <button className="dm-primary" disabled={busy}>Submit report</button></form>;
}

function Actions({ incident, ref_, open, availableUnits, busy, act, setSelected }) {
  const [verify, setVerify] = useState({ zone_id: '', severity: 'MODERATE', note: '' });
  const [dispatch, setDispatch] = useState('');
  const [alloc, setAlloc] = useState({ resource_id: '', quantity: 10 });
  const [closeNote, setCloseNote] = useState('');
  const id = incident.id, me = ref_.me.name;
  return <div className="rs-actions">
    {incident.status === 'REPORTED' && <div className="rs-action"><h4>Verify or reject this report</h4>
      <div className="rs-inline"><Field label="Zone"><select value={verify.zone_id} onChange={e => setVerify({ ...verify, zone_id: e.target.value })}><option value="">Choose…</option>{ref_.zones.map(z => <option key={z.id} value={z.id}>{z.zone_name}</option>)}</select></Field>
        <Field label="Severity"><select value={verify.severity} onChange={e => setVerify({ ...verify, severity: e.target.value })}>{SEVERITY_ORDER.slice().reverse().map(s => <option key={s}>{s}</option>)}</select></Field>
        <Field label="Note"><input value={verify.note} onChange={e => setVerify({ ...verify, note: e.target.value })} placeholder="Stored in the timeline" /></Field></div>
      <div className="dm-row"><button className="dm-primary" disabled={busy || !verify.zone_id} onClick={() => act('Verify an incident', () => post(`/api/response/incidents/${id}/verify`, { ...verify, zone_id: Number(verify.zone_id) }, { person: me }))}>Verify</button>
        <button className="dm-btn" disabled={busy} onClick={() => act('Reject a report', () => post(`/api/response/incidents/${id}/reject`, { note: verify.note }, { person: me }))}>Reject</button></div></div>}
    {open && <div className="rs-action"><h4>Dispatch a unit</h4><div className="rs-inline"><Field label="Unit"><select value={dispatch} onChange={e => setDispatch(e.target.value)}><option value="">Choose…</option>
      {ref_.units.map(u => <option key={u.id} value={u.id}>{u.unit_name} — {u.availability_status}</option>)}</select></Field>
      <button className="dm-primary" disabled={busy || !dispatch} onClick={() => act('Dispatch a unit', () => post(`/api/response/incidents/${id}/dispatch`, { unit_id: Number(dispatch) }, { person: me }))}>Dispatch</button></div>
      <p className="rs-muted">{availableUnits.length} of {ref_.units.length} units are available. Choosing a busy one shows the database refusing it.</p></div>}
    {open && <div className="rs-action"><h4>Allocate relief</h4><div className="rs-inline"><Field label="Item"><select value={alloc.resource_id} onChange={e => setAlloc({ ...alloc, resource_id: e.target.value })}><option value="">Choose…</option>
      {ref_.resources.map(r => <option key={r.id} value={r.id}>{r.resource_name} — {r.quantity_available} ({r.stock_status})</option>)}</select></Field>
      <Field label="Quantity"><input type="number" min="1" value={alloc.quantity} onChange={e => setAlloc({ ...alloc, quantity: e.target.value })} /></Field>
      <button className="dm-primary" disabled={busy || !alloc.resource_id} onClick={() => act('Allocate relief', () => post(`/api/response/incidents/${id}/allocations`, { resource_id: Number(alloc.resource_id), quantity: Number(alloc.quantity) }, { person: me }))}>Allocate</button></div></div>}
    {['VERIFIED', 'RESPONDING', 'RESOLVED'].includes(incident.status) && <div className="rs-action"><h4>Close the incident</h4><div className="rs-inline"><Field label="Closing note"><input value={closeNote} onChange={e => setCloseNote(e.target.value)} placeholder="Stored with the CLOSED entry" /></Field>
      <button className="dm-btn" disabled={busy} onClick={() => act('Close an incident', () => post(`/api/response/incidents/${id}/close`, { note: closeNote }, { person: me }))}>Close incident</button></div>
      <p className="rs-muted">A cursor inside sp_close_incident releases every unit still on this incident.</p></div>}
    <div className="rs-action"><h4>Delete this incident</h4><button className="dm-btn danger" disabled={busy} onClick={() => act('Delete an incident', () => del(`/api/response/incidents/${id}`, { person: me }), () => null)}>Delete</button>
      <p className="rs-muted">Allowed only when it has no dispatch or allocation history (ON DELETE RESTRICT).</p></div>
  </div>;
}

function Restock({ resources, busy, act, person }) {
  const [form, setForm] = useState({ resource_id: '', quantity: 50 });
  return <div className="dm-panel"><h3>Adjust relief stock <small className="rs-muted">administrator</small></h3><div className="rs-inline">
    <Field label="Item"><select value={form.resource_id} onChange={e => setForm({ ...form, resource_id: e.target.value })}><option value="">Choose…</option>{resources.map(r => <option key={r.id} value={r.id}>{r.resource_name} — {r.quantity_available} ({r.stock_status})</option>)}</select></Field>
    <Field label="Change (+ add, − remove)"><input type="number" value={form.quantity} onChange={e => setForm({ ...form, quantity: e.target.value })} /></Field>
    <button className="dm-primary" disabled={busy || !form.resource_id} onClick={() => act('Adjust relief stock', () => post(`/api/response/resources/${form.resource_id}/restock`, { quantity: Number(form.quantity) }, { person }))}>Apply</button></div></div>;
}
