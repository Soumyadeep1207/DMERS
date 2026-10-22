import React, { useEffect, useState } from 'react';
import { get } from '../api.js';
import { Chip, Notice, Section, message } from './labUi.jsx';

const show = outcome => (outcome.outcome === 'refused' ? <Chip tone="bad">refused {outcome.sqlstate}</Chip> : <strong>{String(outcome.outcome)}</strong>);

/** Idea 2: row-level security. The same SQL gives different answers per account type; no WHERE names the user. */
export default function AccessLab() {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => { (async () => { const r = await get('/api/response/lab/rls'); if (r.ok) setData(r.body); else setError(message(r)); })(); }, []);
  if (!data) return <Section eyebrow="Access control" title="Row-level security"><Notice tone="bad">{error || 'Running the probes…'}</Notice></Section>;
  const baselineKey = { 'Incidents visible': 'Incidents visible', 'Timeline entries visible': 'Timeline entries visible', 'Dispatches visible': 'Dispatches visible', 'Allocations visible': 'Allocations visible' };
  return <Section eyebrow="Database lab 2 · row-level security" title="Who may see or change which rows"
    why="Policies on the tables read the acting user from the session variable dmers.actor_id. The probes below ran identical SQL after SET LOCAL ROLE dmers_rls, once per account type, and were rolled back. No query contains a WHERE clause about the user.">
    <div className="dm-table-wrap"><table className="dm-table dm-dense">
      <thead><tr><th>Same SQL, run as…</th><th>Application role (owner)</th>{data.subjects.map(s => <th key={s.person.account_type}>{s.person.account_type}<br /><small>{s.person.name}</small></th>)}</tr></thead>
      <tbody>{data.probes.map((p, i) => <tr key={p.label}><td><strong>{p.label}</strong><br /><code className="rs-sql">{p.sql}</code></td>
        <td>{baselineKey[p.label] ? <strong>{data.owner_baseline[p.label]}</strong> : <span className="rs-muted">not tested</span>}</td>
        {data.subjects.map(s => <td key={s.person.account_type}>{show(s.outcomes[i])}</td>)}</tr>)}</tbody></table></div>
    <p className="rs-muted">{data.how}</p>
    <details><summary>Honest limits</summary><ul className="rs-hints">
      <li>The application's own database role owns the tables and is exempt (RLS is enabled, not forced), so every existing screen behaves as before. Running the API itself under <code>dmers_rls</code> is the next step.</li>
      <li>dmers.actor_id is set by the application. A flaw that lets an attacker run arbitrary SQL could set it too; RLS narrows the damage of ordinary bugs, it is not a defence against a fully compromised connection.</li>
      <li>Column privileges hide <code>users.password</code> from the restricted role entirely (the "refused 42501" row).</li></ul></details>
  </Section>;
}
