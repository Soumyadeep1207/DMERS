import React, { useState } from 'react';
import { get } from '../api.js';
import { Chip, Field, Notice, Section, Table, message, useBusy } from './labUi.jsx';

/** Idea 9: a public statistics release with small-cell suppression and optional Laplace noise. */
export default function PrivacyLab() {
  const [p, setP] = useState({ source: 'history', k: 5, epsilon: '', seed: '' });
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [busy, guard] = useBusy();
  const query = () => new URLSearchParams(Object.entries(p).filter(([, v]) => v !== ''));
  const run = guard(async () => { const r = await get(`/api/response/lab/privacy?${query()}`); if (r.ok) { setData(r.body); setError(''); } else { setData(null); setError(message(r)); } });
  const csv = async () => {
    const token = localStorage.getItem('dmers-token');
    const response = await fetch(`/api/response/lab/privacy?${query()}&format=csv`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!response.ok) return setError('The CSV could not be created.');
    const url = URL.createObjectURL(await response.blob());
    const a = document.createElement('a'); a.href = url; a.download = 'dmers-public-export.csv'; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const s = data?.summary;
  return <Section eyebrow="Database lab 9 · privacy" title="Privacy-safe public export"
    why="Counts per zone, incident type and month are safe to publish only if small cells cannot single out a household. Cells below k are suppressed; with epsilon set, Laplace noise of scale 1/epsilon is added to every count first (differential privacy for counting queries).">
    <div className="rs-inline">
      <Field label="Source"><select value={p.source} onChange={e => setP({ ...p, source: e.target.value })}><option value="history">Synthetic history</option><option value="live">Live incidents (14)</option></select></Field>
      <Field label="k (suppress cells below)"><input type="number" min="1" max="100" value={p.k} onChange={e => setP({ ...p, k: e.target.value })} /></Field>
      <Field label="epsilon (blank = no noise)"><input type="number" min="0.05" max="10" step="0.05" value={p.epsilon} onChange={e => setP({ ...p, epsilon: e.target.value })} placeholder="e.g. 1" /></Field>
      <Field label="Seed (repeatable noise)"><input type="number" min="-1" max="1" step="0.05" value={p.seed} onChange={e => setP({ ...p, seed: e.target.value })} placeholder="optional" /></Field>
      <button className="dm-primary" onClick={run} disabled={busy}>Prepare release</button>
      {data && <button className="dm-btn" onClick={csv}>Download CSV</button>}
    </div>
    {error && <Notice tone="bad">{error}</Notice>}
    {s && <>
      <div className="rs-inline"><Chip tone="info">{s.cells} cells</Chip><Chip tone={s.suppressed_percent > 50 ? 'warn' : 'ok'}>{s.suppressed_cells} suppressed ({s.suppressed_percent}%)</Chip>
        <Chip>released total {s.released_total}</Chip>{data.admin_view && <><Chip>true total {s.true_total}</Chip><Chip tone="info">mean error {s.mean_abs_error ?? '—'} per cell</Chip></>}</div>
      <Table columns={data.admin_view ? ['Zone', 'Type', 'Month', 'True (admin only)', 'Released'] : ['Zone', 'Type', 'Month', 'Released']}
        rows={data.rows.slice(0, 60).map(r => [r.zone_name, r.incident_type, r.month.slice(0, 7), ...(data.admin_view ? [r.true_count] : []),
          r.suppressed ? <Chip tone="muted">suppressed</Chip> : <strong>{r.released_count}</strong>])} />
      <p className="rs-muted">Showing 60 of {data.row_count} cells. {data.method} Citizens see only the released columns.</p>
    </>}
    <details><summary>What this does not promise</summary><ul className="rs-hints">
      <li>Suppression alone does not stop differencing (two overlapping releases can reveal a small count); noise with a recorded epsilon is the stronger tool, and the epsilon of repeated releases adds up.</li>
      <li>The live source has only 14 incidents, so with k = 5 every cell is suppressed: that is the mechanism working, not a bug.</li></ul></details>
  </Section>;
}
