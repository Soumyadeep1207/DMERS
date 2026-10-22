import React, { useCallback, useEffect, useState } from 'react';
import { get, post } from '../api.js';
import { Chip, Field, Notice, Section, Table, isAdministrator, message, useBusy } from './labUi.jsx';
import { formatBytes, planBars, speedup } from './labLogic.js';

/** Idea 6: real EXPLAIN (ANALYZE, BUFFERS) plans on synthetic history: index, BRIN, partition pruning, materialised view. */
export default function OptimiserLab() {
  const [cat, setCat] = useState(null);
  const [rows, setRows] = useState(200000);
  const [results, setResults] = useState({});            // experiment -> { variant: result }
  const [open, setOpen] = useState(null);
  const [notice, setNotice] = useState({ tone: '', text: '' });
  const [busy, guard] = useBusy();
  const admin = isAdministrator();

  const load = useCallback(async () => { const r = await get('/api/response/lab/query/catalog'); if (r.ok) setCat(r.body); else setNotice({ tone: 'bad', text: message(r) }); }, []);
  useEffect(() => { load(); }, [load]);

  const loadHistory = guard(async () => {
    setNotice({ tone: '', text: `Generating ${Number(rows).toLocaleString()} synthetic incidents inside PostgreSQL…` });
    const r = await post('/api/response/lab/query/load', { rows: Number(rows) });
    setNotice(r.ok ? { tone: 'ok', text: `${r.body.rows.toLocaleString()} synthetic rows in the flat table and the monthly-partitioned copy. ${r.body.note}` } : { tone: 'bad', text: message(r) });
    setResults({}); await load();
  });
  const run = async (experiment, variant) => {
    const r = await post('/api/response/lab/query/run', { experiment, variant });
    if (!r.ok) { setNotice({ tone: 'bad', text: message(r) }); return null; }
    setResults(prev => ({ ...prev, [experiment]: { ...prev[experiment], [variant]: r.body } }));
    return r.body;
  };
  const runAll = (exp) => guard(async () => { for (const v of exp.variants) await run(exp.key, v.key); })();

  if (!cat) return <Section eyebrow="Performance" title="Query optimiser"><Notice tone="bad">{notice.text || 'Loading…'}</Notice></Section>;
  const status = cat.status, ready = status.flat_rows > 0;
  return <Section eyebrow="Database lab 6 · EXPLAIN ANALYZE" title="Query-optimiser laboratory"
    why="The same rows are stored twice: as one heap table and range-partitioned by month. Each run builds the variant's index inside a transaction, executes EXPLAIN (ANALYZE, BUFFERS) and rolls back, so every run starts from the same state. The data is synthetic and says so.">
    <div className="rs-inline">
      <Field label="Synthetic incidents to generate"><input type="number" min="1000" max="1000000" step="1000" value={rows} onChange={e => setRows(e.target.value)} disabled={!admin} /></Field>
      {admin ? <button className="dm-primary" onClick={loadHistory} disabled={busy}>{ready ? 'Regenerate' : 'Load'} synthetic history</button> : <span className="rs-muted">An administrator loads the data.</span>}
      <span className="rs-muted">{ready ? `${status.flat_rows.toLocaleString()} rows · table ${formatBytes(status.flat_bytes)} · materialised view ${status.view_populated ? 'populated' : 'empty'}` : 'No history loaded yet.'}</span>
    </div>
    <Notice tone={notice.tone}>{notice.text}</Notice>
    {ready && cat.experiments.map(exp => {
      const done = results[exp.key] || {};
      const keys = exp.variants.filter(v => done[v.key]);
      const slowest = Math.max(...keys.map(v => done[v.key].execution_ms), 0);
      const first = done[exp.variants[0].key];
      return <div className="rs-form" key={exp.key}>
        <h3>{exp.title}</h3><p className="rs-muted">{exp.question}</p>
        <div className="rs-inline">{exp.variants.map(v => <button key={v.key} className="dm-btn" onClick={() => guard(() => run(exp.key, v.key))()} disabled={busy}>{v.label}</button>)}
          <button className="dm-primary" onClick={() => runAll(exp)} disabled={busy}>Run all</button></div>
        {keys.length > 0 && <Table columns={['Variant', 'Execution', 'vs first', 'Scan type', 'Partitions', 'Buffers hit/read', 'Index size', 'Plan']}
          rows={keys.map(v => { const r = done[v.key]; return [v.label,
            <div><strong>{r.execution_ms} ms</strong><div className="lab-bar"><span style={{ width: `${Math.max(2, 100 * r.execution_ms / (slowest || 1))}%` }} /></div></div>,
            first && r !== first ? speedup(first.execution_ms, r.execution_ms) : '—', r.scan_types.join(', '), r.relations_scanned.length > 1 || r.partitions_scanned ? r.partitions_scanned || r.relations_scanned.length : '—',
            `${r.buffers_hit} / ${r.buffers_read}`, formatBytes(r.index_bytes), <button className="dm-btn" onClick={() => setOpen(open === `${exp.key}.${v.key}` ? null : `${exp.key}.${v.key}`)}>{open === `${exp.key}.${v.key}` ? 'Hide' : 'Show'}</button>]; })} />}
        {keys.map(v => open === `${exp.key}.${v.key}` && <div key={v.key}><p className="rs-muted">{done[v.key].label}: <code className="rs-sql">{done[v.key].sql}</code></p>
          <ul className="lab-plan">{planBars(done[v.key].nodes).map((n, i) => <li key={i} style={{ marginLeft: n.depth * 18 }}>
            <strong>{n.node}</strong>{n.relation ? ` on ${n.relation}` : ''}{n.index ? ` using ${n.index}` : ''}
            <span className="rs-muted"> · {n.rows} row(s) × {n.loops} · {n.ms} ms{n.rows_removed ? ` · ${n.rows_removed} removed by filter` : ''}</span>
            <div className="lab-bar"><span style={{ width: `${n.share}%` }} /></div></li>)}</ul></div>)}
      </div>;
    })}
    <details><summary>How to read this</summary><ul className="rs-hints">
      <li>Timings are for this machine and this moment; compare the ratios and the plan shapes, not the milliseconds.</li>
      <li>BRIN is only useful because the rows were loaded in time order (high physical correlation). On shuffled data it would not help.</li>
      <li>Partition pruning shows as "Partitions: 1": the planner skipped the other months. The real incident_updates table is deliberately NOT partitioned: it is small, append-only and referenced by foreign keys.</li>
      <li>The materialised view trades freshness for speed: it must be refreshed (REFRESH MATERIALIZED VIEW CONCURRENTLY) when the history changes.</li></ul></details>
    {status.flat_rows > 0 && <Chip tone="info">parallel workers disabled for readability</Chip>}
  </Section>;
}
