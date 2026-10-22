import React, { useCallback, useEffect, useState } from 'react';
import { get, post } from '../api.js';
import { Chip, Notice, Section, Table, isAdministrator, message, useBusy } from './labUi.jsx';
import { shortHash } from './labLogic.js';

/** Idea 1: the incident timeline is a SHA-256 hash chain, so edits made behind the triggers' backs are detectable. */
export default function ChainLab() {
  const [overview, setOverview] = useState(null);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [notice, setNotice] = useState({ tone: '', text: '' });
  const [tampered, setTampered] = useState(null);
  const [edit, setEdit] = useState({ update_no: 2, note: 'Nothing unusual happened.' });
  const [busy, guard] = useBusy();
  const admin = isAdministrator();

  const load = useCallback(async () => {
    const r = await get('/api/response/lab/chain');
    if (r.ok) setOverview(r.body); else setNotice({ tone: 'bad', text: message(r) });
  }, []);
  const open = useCallback(async id => {
    setSelected(id);
    const r = await get(`/api/response/lab/chain/${id}`);
    setDetail(r.ok ? r.body.entries : null);
  }, []);
  useEffect(() => { load(); }, [load]);

  const act = (path, body, done) => guard(async () => {
    const r = await post(path, body);
    setNotice({ tone: r.ok ? 'ok' : 'bad', text: r.ok ? done(r.body) : message(r) });
    if (r.ok) { await load(); if (selected) await open(selected); }
    return r;
  })();

  const tamper = async () => {
    const r = await act('/api/response/lab/chain/tamper', { incident_id: selected, ...edit }, b => `Entry ${b.update_no} of incident #${b.incident_id} was rewritten with the append-only trigger bypassed. Now verify.`);
    if (r?.ok) setTampered({ incident_id: selected, update_no: Number(edit.update_no), note: r.body.previous_note });
  };
  const restore = async () => {
    const r = await act('/api/response/lab/chain/restore', tampered, () => 'The original wording was put back: the chain verifies again.');
    if (r?.ok) setTampered(null);
  };

  if (!overview) return <Section eyebrow="Integrity" title="Tamper-evident timeline"><Notice tone="bad">{notice.text || 'Loading…'}</Notice></Section>;
  return <Section eyebrow="Database lab 1 · pgcrypto" title="Tamper-evident incident timeline"
    why="The append-only trigger stops ordinary SQL from editing history, but a superuser can switch triggers off. Each timeline entry therefore stores SHA-256(previous hash + its own content). Change one entry and every later link stops matching.">
    <div className="rs-inline">
      <button className="dm-primary" onClick={guard(load)} disabled={busy}>Verify all chains now</button>
      {admin && <button className="dm-btn" onClick={() => act('/api/response/lab/chain/anchor', {}, b => `${b.anchored} chain heads were anchored. Deleting the newest entries later will now be detected.`)} disabled={busy}>Anchor current heads</button>}
      <Chip tone={overview.broken ? 'bad' : 'ok'}>{overview.broken ? `${overview.broken} chain(s) BROKEN` : 'all chains intact'}</Chip>
      <span className="rs-muted">{overview.entries_checked} entries in {overview.incidents_checked} incidents · {overview.anchors.anchored} anchored</span>
    </div>
    <Notice tone={notice.tone}>{notice.text}</Notice>
    <div className="rs-grid">
      <div>
        <Table columns={['Incident', 'Entries', 'Chain', 'First bad entry', 'What is wrong', 'Head hash']}
          rows={overview.incidents.map(i => [
            <button className={`dm-btn${selected === i.incident_id ? ' active' : ''}`} onClick={() => open(i.incident_id)}>#{i.incident_id}</button>,
            i.entries, <Chip tone={i.intact ? 'ok' : 'bad'}>{i.intact ? 'intact' : 'BROKEN'}</Chip>, i.first_bad_update_no, i.problem, <code>{shortHash(i.head_hash)}</code>])} />
      </div>
      <div className="rs-form">
        <h3>{selected ? `Incident #${selected}: the chain, entry by entry` : 'Select an incident'}</h3>
        {detail && <Table columns={['#', 'Status', 'Note', 'prev_hash', 'row_hash', 'Content', 'Link']}
          rows={detail.map(e => [e.update_no, e.new_status, e.note, <code>{shortHash(e.prev_hash)}</code>, <code>{shortHash(e.row_hash)}</code>,
            <Chip tone={e.content_ok ? 'ok' : 'bad'}>{e.content_ok ? 'ok' : 'CHANGED'}</Chip>, <Chip tone={e.link_ok ? 'ok' : 'bad'}>{e.link_ok ? 'ok' : 'BROKEN'}</Chip>])} />}
        {admin && selected && <>
          <h3>Attack it (administrator, demo mode)</h3>
          <p className="rs-muted">Runs <code>SET LOCAL session_replication_role = replica</code>, which a superuser may do, and rewrites one note. The trace shows that no trigger fired.</p>
          <div className="rs-inline">
            <label className="rs-field"><span>Entry no.</span><input type="number" min="1" value={edit.update_no} onChange={e => setEdit({ ...edit, update_no: e.target.value })} /></label>
            <label className="rs-field grow"><span>New wording</span><input value={edit.note} onChange={e => setEdit({ ...edit, note: e.target.value })} maxLength={200} /></label>
            <button className="dm-btn" onClick={tamper} disabled={busy}>Rewrite history</button>
            {tampered && <button className="dm-btn" onClick={restore} disabled={busy}>Restore original</button>}
          </div>
        </>}
      </div>
    </div>
    <details><summary>What this does and does not protect</summary>
      <ul className="rs-hints"><li>Detects an edited note, status or time, a removed middle entry and an inserted entry (numbering gap).</li>
        <li>Deleting the newest entries is only detected if the head was anchored first. Publish anchors outside the database (print them, e-mail them) for a stronger guarantee.</li>
        <li>Someone who can rewrite the whole chain and recompute every hash cannot be stopped by the chain alone; this is evidence, not prevention.</li></ul></details>
  </Section>;
}
