import React, { useState, useSyncExternalStore } from 'react';
import { clearActivity, getActivity, subscribeActivity } from './api.js';
import { describeTrace } from './trace.js';

/** One operation explained as the five questions of the course guidelines. */
export function TraceCard({ entry, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  const view = describeTrace(entry.trace, entry.message);
  if (!view) return null;
  const failed = view.outcome !== 'COMMITTED';
  return <article className={`rs-trace ${failed ? 'refused' : 'committed'}`}>
    <header onClick={() => setOpen(value => !value)} role="button" tabIndex={0} onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && setOpen(value => !value)} aria-expanded={open}>
      <span className="rs-outcome">{view.outcome}</span>
      <b>{entry.label}</b>
      <small>{entry.person ? `${entry.person} · ` : ''}{entry.method} {entry.path.replace('/api/response', '')} · HTTP {entry.status}</small>
    </header>
    {open && <div className="rs-trace-body">
      <dl>{view.answers.map(({ question, answer }) => <React.Fragment key={question}>
        <dt>{question}</dt>
        <dd>{answer.map((line, i) => <div key={i}>{line}</div>)}</dd>
      </React.Fragment>)}</dl>
      {view.statements.length > 0 && <details><summary>SQL statements ({view.statements.length}, placeholders only, never values)</summary>
        <ol className="rs-sql">{view.statements.map((s, i) => <li key={i}><code>{s}</code><em>{view.statementStatus[i]}</em></li>)}</ol></details>}
      {view.details.length > 0 && <details><summary>What each component does</summary>
        <ul className="rs-notes">{view.details.map(d => <li key={`${d.kind}-${d.name}`}><b>{d.kind} {d.name}</b>{d.fires ? ` (${d.fires})` : ''}{d.note ? `: ${d.note}` : ''}</li>)}</ul></details>}
      {view.constraints.length > 0 && <details><summary>Constraints on the tables written ({view.constraints.length})</summary><p className="rs-muted">{view.constraints.join(' · ')}</p></details>}
    </div>}
  </article>;
}

/** Collapsible drawer listing every recent database operation, newest first. */
export default function ActivityPanel() {
  const entries = useSyncExternalStore(subscribeActivity, getActivity, getActivity);
  const [open, setOpen] = useState(false);
  return <>
    <button className="rs-drawer-toggle" onClick={() => setOpen(value => !value)} aria-expanded={open} aria-controls="rs-activity">
      Database activity{entries.length ? ` (${entries.length})` : ''}
    </button>
    <aside id="rs-activity" className={`rs-drawer ${open ? 'open' : ''}`} aria-label="Database activity" aria-hidden={!open}>
      <header><div><p className="dm-eyebrow">Database activity</p><h3>What the database just did</h3></div>
        <div className="dm-row"><button className="dm-btn small" onClick={clearActivity} disabled={!entries.length}>Clear</button><button className="dm-btn small" onClick={() => setOpen(false)}>Close</button></div></header>
      <p className="rs-muted">User operation → SQL / PL-pgSQL → database processing → update or retrieval → result. Open an entry to see the five questions.</p>
      {!entries.length && <div className="dm-empty"><b>No operations yet</b><p>Report, verify, dispatch or allocate something and each transaction appears here.</p></div>}
      <div className="rs-trace-list">{entries.map((entry, index) => <TraceCard key={entry.id} entry={entry} defaultOpen={index === 0} />)}</div>
    </aside>
  </>;
}
