import React, { useCallback, useEffect, useState } from 'react';
import { get, post } from '../api.js';
import { Chip, Field, Notice, Section, Table, isAdministrator, message, useBusy } from './labUi.jsx';
import { fitPath } from './labLogic.js';

const minutes = seconds => (seconds === null || seconds === undefined ? '—' : `${(seconds / 60).toFixed(1)} min`);
const km = metres => (metres === null || metres === undefined ? '—' : `${(metres / 1000).toFixed(2)} km`);

/** Idea 5: nearest-facility KNN, hazard closures and A* run inside PostgreSQL, checked against the Python search. */
export default function RoutingLab() {
  const [status, setStatus] = useState(null);
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [block, setBlock] = useState(false);
  const [kind, setKind] = useState('hospital');
  const [result, setResult] = useState(null);
  const [nearest, setNearest] = useState(null);
  const [notice, setNotice] = useState({ tone: '', text: '' });
  const [busy, guard] = useBusy();
  const admin = isAdministrator();

  const load = useCallback(async () => {
    const r = await get('/api/response/lab/routing/status');
    if (!r.ok) return setNotice({ tone: 'bad', text: message(r) });
    setStatus(r.body);
    const fire = r.body.facilities.find(f => f.kind === 'fire_station'), hospital = r.body.facilities.find(f => f.kind === 'hospital');
    setFrom(f => f || fire?.id || ''); setTo(t => t || hospital?.id || '');
  }, []);
  useEffect(() => { load(); }, [load]);
  const place = id => status?.facilities.find(f => f.id === id);

  const loadGraph = guard(async () => { const r = await post('/api/response/lab/routing/load', {}); setNotice(r.ok ? { tone: 'ok', text: `Loaded ${r.body.loaded.nodes} nodes, ${r.body.loaded.edges} road segments and ${r.body.loaded.facilities} facilities into PostgreSQL.` } : { tone: 'bad', text: message(r) }); await load(); });
  const request = (hazards = []) => ({ from_lat: place(from).lat, from_lon: place(from).lon, to_lat: place(to).lat, to_lon: place(to).lon, hazards });
  const route = guard(async () => {
    setNotice({ tone: '', text: 'Searching in PostgreSQL, then in Python…' });
    let r = await post('/api/response/lab/routing/route', request());
    if (r.ok && block) {
      const mid = r.body.database.path[Math.floor(r.body.database.path.length / 2)];
      const clear = r.body;
      r = await post('/api/response/lab/routing/route', request([{ lat: mid[0], lon: mid[1] }]));
      if (r.ok) r.body.clearPath = clear.database.path;
      if (r.ok) r.body.hazard = mid;
    }
    if (r.ok) { setResult(r.body); setNotice({ tone: r.body.same_answer ? 'ok' : 'bad', text: r.body.same_answer ? 'PostgreSQL and Python found the same fastest route.' : 'The two implementations disagree: investigate.' }); }
    else setNotice({ tone: 'bad', text: message(r) });
  });
  const candidates = guard(async () => {
    const p = place(to);
    const r = await post('/api/response/lab/routing/nearest', { lat: p.lat, lon: p.lon, kind, k: 3, hazards: [] });
    if (r.ok) setNearest(r.body); else setNotice({ tone: 'bad', text: message(r) });
  });

  if (!status) return <Section eyebrow="Spatial" title="Routing inside the database"><Notice tone="bad">{notice.text || 'Loading…'}</Notice></Section>;
  const drawn = result ? fitPath([...(result.clearPath || []), ...result.database.path], 560, 320) : null;
  const polyline = points => points.map(p => drawn.project(p).map(v => v.toFixed(1)).join(',')).join(' ');
  return <Section eyebrow="Database lab 5 · cube + earthdistance + PL/pgSQL" title="Nearest unit and fastest route computed by PostgreSQL"
    why="The Vellore road graph (OpenStreetMap, offline) is stored in tables. Nearest road node and nearest facility use a GiST k-nearest-neighbour index; road blocks close segments by distance; A* is a PL/pgSQL function. The same question is answered by the Python search and the two results are compared. PostGIS and pgRouting are not needed.">
    {!status.loaded ? <div className="rs-inline"><p className="rs-muted">The road graph is not in PostgreSQL yet.</p>{admin ? <button className="dm-primary" onClick={loadGraph} disabled={busy}>Load road graph into PostgreSQL</button> : <span className="rs-muted">Ask an administrator to load it.</span>}</div> : <>
      <div className="rs-inline">
        <Field label="From"><select value={from} onChange={e => setFrom(e.target.value)}>{status.facilities.map(f => <option key={f.id} value={f.id}>{f.name} ({f.kind.replace('_', ' ')})</option>)}</select></Field>
        <Field label="To"><select value={to} onChange={e => setTo(e.target.value)}>{status.facilities.map(f => <option key={f.id} value={f.id}>{f.name} ({f.kind.replace('_', ' ')})</option>)}</select></Field>
        <label className="rs-field"><span>Road block</span><input type="checkbox" checked={block} onChange={e => setBlock(e.target.checked)} /></label>
        <button className="dm-primary" onClick={route} disabled={busy || !from || !to}>Route in PostgreSQL and in Python</button>
        <span className="rs-muted">{status.nodes} nodes · {status.edges} segments · {status.facilities.length} facilities</span>
      </div>
      <Notice tone={notice.tone}>{notice.text}</Notice>
      {result && <div className="rs-grid">
        <Table columns={['', 'PostgreSQL (A* in PL/pgSQL)', 'Python (road_network.py)']} rows={[
          ['Travel time', minutes(result.database.seconds), minutes(result.python.seconds)], ['Distance', km(result.database.metres), km(result.python.metres)],
          ['Road segments', result.database.segments, result.python.segments], ['Nodes expanded', result.database.nodes_explored, result.python.nodes_explored],
          ['Segments closed by the block', result.database.closed_segments, result.python.closed_segments], ['Run time', `${result.database.runtime_ms} ms`, `${result.python.runtime_ms} ms`],
          ['Same answer?', <Chip tone={result.same_answer ? 'ok' : 'bad'}>{result.same_answer ? 'yes' : 'NO'}</Chip>, '']]} />
        <svg viewBox="0 0 560 320" className="lab-map" role="img" aria-label="Route computed in PostgreSQL">
          {result.clearPath && <polyline points={polyline(result.clearPath)} fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray="5 5" opacity=".5" />}
          <polyline points={polyline(result.database.path)} fill="none" stroke="var(--dm-accent)" strokeWidth="3.5" strokeLinejoin="round" />
          {result.hazard && (() => { const [x, y] = drawn.project(result.hazard); return <g><circle cx={x} cy={y} r="10" fill="none" stroke="var(--dm-severe)" strokeWidth="3" /><line x1={x - 7} y1={y - 7} x2={x + 7} y2={y + 7} stroke="var(--dm-severe)" strokeWidth="3" /></g>; })()}
          {(() => { const [x, y] = drawn.project(result.database.path[0]); return <circle cx={x} cy={y} r="5" fill="currentColor" />; })()}
          {(() => { const [x, y] = drawn.project(result.database.path[result.database.path.length - 1]); return <rect x={x - 5} y={y - 5} width="10" height="10" fill="currentColor" />; })()}
        </svg>
      </div>}
      {result && <p className="rs-muted">{result.note} Drawn: solid line = route in PostgreSQL{result.clearPath ? '; dashed = route without the block; ✕ = road block' : ''}; circle = start, square = destination.</p>}
      <h3>Straight-line rank versus driving rank</h3>
      <div className="rs-inline">
        <Field label="Incident at the destination above; find nearest"><select value={kind} onChange={e => setKind(e.target.value)}>{status.facility_kinds.map(k => <option key={k.kind} value={k.kind}>{k.kind.replace('_', ' ')} ({k.n})</option>)}</select></Field>
        <button className="dm-btn" onClick={candidates} disabled={busy || !to}>Rank 3 nearest by road</button>
      </div>
      {nearest && <><Table columns={['Facility', 'Straight-line distance', 'Straight-line rank', 'Driving time', 'Driving rank']}
        rows={nearest.candidates.map(c => [c.name, km(c.straight_line_m), c.straight_rank, minutes(c.drive_seconds), <strong>{c.drive_rank ?? '—'}</strong>])} />
        <p className="rs-muted">{nearest.straight_line_winner_differs ? 'The closest on the map is NOT the quickest by road here.' : 'Here the closest on the map is also the quickest by road.'} {nearest.note}</p></>}
    </>}
    <details><summary>Scope and honesty</summary><ul className="rs-hints">
      <li>Parity is exact for road blocks (a 35 m closure circle, no slowdown factor). The Python layer's fire/flood exposure weighting and weather speeds are not reimplemented in SQL.</li>
      <li>Travel times are planning estimates from road class and posted speed, not live traffic.</li>
      <li>Python is far faster here (milliseconds against about 2.5 seconds): PL/pgSQL pays SQL overhead for every expanded node. The value of the database version is one source of truth next to the data, not speed.</li>
      <li>A facility with no driving route to the point (one-way streets, closures) shows "—" for time and no rank.</li></ul></details>
  </Section>;
}
