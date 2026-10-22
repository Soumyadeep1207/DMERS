import React, { useCallback, useEffect, useState } from 'react';
import { get, post } from '../api.js';
import { Chip, Field, Notice, Section, Table, message, time, useBusy } from './labUi.jsx';
import { localToApi } from './labLogic.js';

const PURPOSES = ['STANDBY', 'TRAINING', 'MAINTENANCE', 'EXERCISE'];
const istWall = ms => new Date(ms + 330 * 60000).toISOString().slice(0, 16);          // wall-clock time in India for an instant
const defaultStart = () => `${istWall(Date.now() + 86400000).slice(0, 10)}T08:00`;
const plusHours = (value, hours) => { const d = new Date(`${value}:00Z`); d.setUTCHours(d.getUTCHours() + hours); return d.toISOString().slice(0, 16); };

/** Idea 4: an EXCLUDE USING gist constraint forbids overlapping bookings of one unit, even under concurrency. */
export default function BookingLab() {
  const [units, setUnits] = useState([]);
  const [list, setList] = useState([]);
  const [free, setFree] = useState(null);
  const [form, setForm] = useState({ unit_id: '', purpose: 'STANDBY', starts: defaultStart(), hours: 12, note: '' });
  const [notice, setNotice] = useState({ tone: '', text: '' });
  const [busy, guard] = useBusy();
  const canBook = (() => { try { return ['official', 'admin'].includes(JSON.parse(localStorage.getItem('dmers-user') || 'null')?.role); } catch { return false; } })();

  const load = useCallback(async () => {
    const [ref, res] = await Promise.all([get('/api/response/reference'), get('/api/response/lab/reservations')]);
    if (ref.ok) { setUnits(ref.body.units); setForm(f => ({ ...f, unit_id: f.unit_id || ref.body.units[0]?.id || '' })); }
    if (res.ok) setList(res.body.reservations); else setNotice({ tone: 'bad', text: message(res) });
  }, []);
  useEffect(() => { load(); }, [load]);

  const book = guard(async (override = {}) => {
    const f = { ...form, ...override };
    const r = await post('/api/response/lab/reservations', { unit_id: Number(f.unit_id), purpose: f.purpose, note: f.note || undefined, starts_at: localToApi(f.starts), ends_at: localToApi(plusHours(f.starts, Number(f.hours))) });
    setNotice(r.ok ? { tone: 'ok', text: `Booked. The database checked ex_reservations_no_overlap and found no overlapping reservation for that unit.` }
      : { tone: 'bad', text: `${message(r)}${r.body.constraint ? ` (constraint ${r.body.constraint}, SQLSTATE ${r.body.sqlstate})` : ''}` });
    await load();
  });
  const cancel = guard(async id => { const r = await post(`/api/response/lab/reservations/${id}/cancel`, {}); setNotice(r.ok ? { tone: 'ok', text: 'Cancelled: the slot is free again.' } : { tone: 'bad', text: message(r) }); await load(); });
  const showFree = guard(async () => {
    const to = plusHours(form.starts, 24);
    const r = await get(`/api/response/lab/reservations/free?${new URLSearchParams({ unit_id: form.unit_id, from: localToApi(form.starts), to: localToApi(to) })}`);
    if (r.ok) setFree(r.body.free_windows); else setNotice({ tone: 'bad', text: message(r) });
  });
  const overlap = () => { const last = list.find(r => r.status === 'BOOKED' && String(r.unit_id) === String(form.unit_id)); if (!last) return setNotice({ tone: '', text: 'Book something for this unit first, then try to overlap it.' }); book({ starts: istWall(new Date(last.starts_at).getTime() + 3600000), hours: 2, purpose: 'TRAINING' }); };

  return <Section eyebrow="Database lab 4 · exclusion constraint" title="Time-range reservations that can never overlap"
    why="A UNIQUE index cannot say 'no two bookings of one unit overlap'. An EXCLUDE USING gist (unit_id WITH =, period WITH &&) constraint can. Two coordinators booking at the same instant cannot both win: the second insert waits for the first to commit and then fails with SQLSTATE 23P01.">
    {canBook ? <div className="rs-inline">
      <Field label="Unit"><select value={form.unit_id} onChange={e => setForm({ ...form, unit_id: e.target.value })}>{units.map(u => <option key={u.id} value={u.id}>{u.unit_name}</option>)}</select></Field>
      <Field label="Purpose"><select value={form.purpose} onChange={e => setForm({ ...form, purpose: e.target.value })}>{PURPOSES.map(p => <option key={p}>{p}</option>)}</select></Field>
      <Field label="Starts (IST)"><input type="datetime-local" value={form.starts} onChange={e => setForm({ ...form, starts: e.target.value })} /></Field>
      <Field label="Hours"><input type="number" min="1" max="72" value={form.hours} onChange={e => setForm({ ...form, hours: e.target.value })} /></Field>
      <button className="dm-primary" onClick={() => book()} disabled={busy || !form.unit_id}>Reserve</button>
      <button className="dm-btn" onClick={overlap} disabled={busy}>Try to overlap the last booking</button>
      <button className="dm-btn" onClick={showFree} disabled={busy}>Free windows (24 h)</button>
    </div> : <Notice>Booking is for coordinators and administrators. You can see the reservations below.</Notice>}
    <Notice tone={notice.tone}>{notice.text}</Notice>
    {free && <p className="rs-muted">Free windows for the chosen unit (range arithmetic in SQL): {free.length ? free.map(w => `${time(w.starts_at)} – ${time(w.ends_at)}`).join('  ·  ') : 'none, fully booked'}</p>}
    <Table columns={['Unit', 'Purpose', 'From (IST)', 'To (IST)', 'Status', 'Booked by', '']}
      rows={list.map(r => [r.unit_name, r.purpose, time(r.starts_at), time(r.ends_at), <Chip tone={r.status === 'BOOKED' ? 'info' : 'muted'}>{r.status}</Chip>, r.booked_by,
        canBook && r.status === 'BOOKED' ? <button className="dm-btn" onClick={() => cancel(r.id)} disabled={busy}>Cancel</button> : null])} empty="No reservations yet." />
    <p className="rs-muted">Periods are half-open [start, end): a booking may start exactly when another ends. Cancelled bookings are ignored by the constraint.</p>
  </Section>;
}
