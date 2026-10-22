import React, { useEffect, useState } from 'react';
import { get, post } from '../api.js';
import { Chip, Field, Notice, Section, message, useBusy } from './labUi.jsx';
import { matrixTone } from './labLogic.js';

const outcome = step => (step.error ? <span><Chip tone="bad">{step.error.sqlstate} {step.error.name}</Chip><br /><small>{step.error.message}</small></span>
  : step.skipped ? <em className="rs-muted">skipped: {step.skipped}</em>
  : step.result === undefined ? null : <code>{typeof step.result === 'string' ? step.result : JSON.stringify(step.result)}</code>);

/** Idea 3: two real sessions, scripted interleaving, every anomaly shown as PostgreSQL really behaves. */
export default function IsolationLab() {
  const [catalog, setCatalog] = useState(null);
  const [pick, setPick] = useState({ scenario: 'lost_update', level: 'READ COMMITTED', mode: 'naive' });
  const [run, setRun] = useState(null);
  const [matrix, setMatrix] = useState(null);
  const [error, setError] = useState('');
  const [busy, guard] = useBusy();
  useEffect(() => { (async () => { const r = await get('/api/response/lab/isolation/catalog'); if (r.ok) setCatalog(r.body); else setError(message(r)); })(); }, []);
  if (!catalog) return <Section eyebrow="Concurrency" title="Isolation levels"><Notice tone="bad">{error || 'Loading…'}</Notice></Section>;
  const scenario = catalog.scenarios.find(s => s.key === pick.scenario);
  const choose = (field, value) => {
    const next = { ...pick, [field]: value };
    if (field === 'scenario') next.mode = catalog.scenarios.find(s => s.key === value).modes[0];
    setPick(next);
  };
  const execute = guard(async () => { const r = await post('/api/response/lab/isolation/run', pick); if (r.ok) { setRun(r.body); setError(''); } else setError(message(r)); });
  const showMatrix = guard(async () => { const r = await get('/api/response/lab/isolation/matrix'); if (r.ok) setMatrix(r.body); else setError(message(r)); });

  return <Section eyebrow="Database lab 3 · transactions" title="Isolation-level anomaly laboratory"
    why="Two real PostgreSQL sessions, A and B, run a fixed interleaving against scratch tables. Change the isolation level and watch which anomalies PostgreSQL allows, which it refuses with SQLSTATE 40001, and how a retry loop recovers.">
    <div className="rs-inline">
      <Field label="Scenario"><select value={pick.scenario} onChange={e => choose('scenario', e.target.value)}>{catalog.scenarios.map(s => <option key={s.key} value={s.key}>{s.title}</option>)}</select></Field>
      <Field label="Isolation level"><select value={pick.level} onChange={e => choose('level', e.target.value)}>{catalog.levels.map(l => <option key={l}>{l}</option>)}</select></Field>
      <Field label="Application style"><select value={pick.mode} onChange={e => choose('mode', e.target.value)}>{scenario.modes.map(m => <option key={m} value={m}>{m}: {scenario.modes_help[m]}</option>)}</select></Field>
      <button className="dm-primary" onClick={execute} disabled={busy}>Run it</button>
      <button className="dm-btn" onClick={showMatrix} disabled={busy}>Run all 12 combinations</button>
    </div>
    <p className="rs-muted">{scenario.story}</p>
    <Notice tone={error ? 'bad' : ''}>{error}</Notice>
    {run && <>
      <Notice tone={run.anomaly ? 'bad' : 'ok'}><strong>{run.anomaly ? 'Anomaly. ' : 'No anomaly. '}</strong>{run.verdict}</Notice>
      <div className="dm-table-wrap"><table className="dm-table dm-dense lab-lanes"><thead><tr><th>#</th><th>Session A</th><th>Session B</th></tr></thead>
        <tbody>{run.steps.map(step => <tr key={step.n}><td>{step.n}</td>
          {['A', 'B'].map(who => <td key={who}>{step.session === who ? <div><code>{step.sql}{step.params.length ? `  [${step.params.join(', ')}]` : ''}</code>{step.note && <div className="rs-muted">{step.note}</div>}<div>{outcome(step)}</div></div> : null}</td>)}</tr>)}</tbody></table></div>
      <p className="rs-muted">Final table state: <code>{JSON.stringify(run.final_state)}</code>{run.retries ? ` · ${run.retries} retry` : ''}</p>
    </>}
    {matrix && <div className="dm-table-wrap"><table className="dm-table dm-dense"><thead><tr><th>Anomaly (naive application code)</th>{matrix.levels.map(l => <th key={l}>{l}</th>)}</tr></thead>
      <tbody>{matrix.matrix.map(row => <tr key={row.scenario}><td><strong>{row.title}</strong></td>{matrix.levels.map(l => <td key={l}><Chip tone={matrixTone(row.levels[l])}>{row.levels[l]}</Chip></td>)}</tr>)}</tbody></table></div>}
    <details><summary>Reading the result</summary><ul className="rs-hints">
      <li>PostgreSQL's READ UNCOMMITTED behaves as READ COMMITTED, so it is not offered. Its REPEATABLE READ is snapshot isolation: it prevents phantoms as well, but still allows write skew.</li>
      <li>"prevented" means PostgreSQL aborted a transaction with 40001. The application must be ready to retry; the retry mode shows that loop.</li></ul></details>
  </Section>;
}
