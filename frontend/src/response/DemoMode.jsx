import React, { useRef, useState } from 'react';
import { call, clearActivity, get, post } from './api.js';
import { PERSONAS, STEPS, newContext } from './demoScript.js';
import { TraceCard } from './ActivityPanel.jsx';

/** Guided walk-through of transactions T1-T10 on fresh demonstration data, including the refusals. */
export default function DemoMode() {
  const [log, setLog] = useState([]);                // finished steps: {step, status, ok, body, entry}
  const [index, setIndex] = useState(0);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const tokens = useRef({});
  const ctx = useRef(null);
  const cursor = useRef(0);                      // the step to run next (a ref, so loops never see a stale value)
  const done = index >= STEPS.length;

  const setup = async () => {
    const personas = await get('/api/response/demo/personas');
    if (!personas.ok) throw new Error(personas.status === 404 ? 'Demo mode is switched off on this server (DMERS_DEMO_MODE).' : personas.body.error || 'Sign in as the administrator to run the demonstration.');
    const byName = Object.fromEntries(personas.body.personas.map(p => [p.name, p]));
    for (const [key, name] of Object.entries(PERSONAS)) {
      const token = await post('/api/response/demo/token', { user_id: byName[name].id });
      if (!token.ok) throw new Error(`Could not act as ${name}: ${token.body.error}`);
      tokens.current[key] = token.body.token;
    }
    const refs = await get('/api/response/reference', { token: tokens.current.coordinator });
    ctx.current = newContext(refs.body);
  };

  const reset = async () => {
    setBusy(true); setError('');
    try {
      const r = await post('/api/response/demo/reset');
      if (!r.ok) throw new Error(r.body.error || 'The demonstration data could not be reloaded.');
      tokens.current = {}; ctx.current = null; cursor.current = 0; setLog([]); setIndex(0); clearActivity();
    } catch (e) { setError(e.message); }
    setBusy(false);
  };

  /** Run exactly one step; returns false when it could not be run at all (setup or network failure). */
  const runOne = async () => {
    try {
      if (!ctx.current) await setup();
      const index = cursor.current;
      const step = STEPS[index];
      const [method, path, body] = step.request(ctx.current);
      const who = step.person ? PERSONAS[step.person] : 'anonymous';
      const result = await call(method, path, body, { token: step.person ? tokens.current[step.person] : null, label: step.title, person: who });
      step.after?.(ctx.current, result.body);
      setLog(items => [{ step, status: result.status, ok: result.status === step.expect, body: result.body, who }, ...items]);
      cursor.current = index + 1;
      setIndex(index + 1);
      return true;
    } catch (e) { setError(e.message); return false; }
  };

  const next = async () => {
    if (done || busy) return;
    setBusy(true); setError('');
    await runOne();
    setBusy(false);
  };

  const runAll = async () => {
    if (busy) return;
    setBusy(true); setError('');
    while (cursor.current < STEPS.length) { if (!(await runOne())) break; }
    setBusy(false);
  };
  const step = STEPS[index];
  const mismatches = log.filter(item => !item.ok).length;

  return <section className="dm-panel rs-demo">
    <div className="dm-panel-head"><p className="dm-eyebrow">Review III demonstration</p><h2>Guided transaction walk-through</h2>
      <p className="dm-muted">Ten transactions on fresh data. At each step the right person acts, the database does its work, and the result is explained as: operation · tables · SQL / PL-pgSQL component · effect on the database · result. Refusals are part of the demonstration: a rolled-back transaction leaves no partial rows.</p></div>
    <div className="dm-row"><button className="dm-btn" onClick={reset} disabled={busy}>Reset demonstration data</button>
      <button className="dm-primary" onClick={next} disabled={busy || done}>{done ? 'Walk-through complete' : `Next step (${index + 1} of ${STEPS.length})`}</button>
      <button className="dm-btn" onClick={runAll} disabled={busy || done}>Run all remaining</button></div>
    {error && <p className="dm-callout warn" role="alert">{error}</p>}
    {!done && <div className="rs-next"><span className="rs-chip info">{step.group}</span><div><b>{step.title}</b><p className="rs-muted">By {step.person ? `${PERSONAS[step.person]} (${step.person})` : 'an anonymous visitor'} · the database should {step.failure ? <b>refuse</b> : 'accept'} this (HTTP {step.expect}). {step.why}</p></div></div>}
    {done && <p className="dm-callout">{mismatches ? `${mismatches} step(s) did not behave as expected.` : 'All steps behaved as expected. Open the Reports tab to see the results of this run.'}</p>}
    <div className="rs-trace-list">{log.map((item, i) => <div key={item.step.id} className="rs-step">
      <p className="rs-step-head"><span className="rs-chip">{item.step.group}</span> <b>{item.step.title}</b> — {item.who} — HTTP {item.status} {item.ok ? '✓ as expected' : '✗ UNEXPECTED'}</p>
      <p className="rs-muted">{item.step.why}</p>
      {item.body.db_trace ? <TraceCard entry={{ label: item.step.title, person: item.who, method: '', path: '', status: item.status, message: item.body.error || '', trace: item.body.db_trace }} defaultOpen={i === 0} />
        : <p className="dm-callout">{item.body.error || 'Refused by the server before reaching the database (permission check).'}</p>}</div>)}</div>
  </section>;
}
