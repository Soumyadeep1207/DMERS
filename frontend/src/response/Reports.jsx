import React, { useEffect, useState } from 'react';
import { get } from './api.js';
import { downloadPdf } from './reportExport.js';

const cell = value => (value === null || value === undefined ? '—' : String(value));

export default function Reports() {
  const [catalogue, setCatalogue] = useState([]);
  const [key, setKey] = useState('');
  const [params, setParams] = useState({});
  const [result, setResult] = useState(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const current = catalogue.find(r => r.key === key);

  useEffect(() => { (async () => {
    const r = await get('/api/response/reports');
    if (r.ok) { setCatalogue(r.body.reports); setKey(r.body.reports[0]?.key || ''); }
    else setMessage(r.status === 403 ? 'Reports are available to coordinators, unit leads and administrators.' : r.body.error || 'Reports could not be loaded.');
  })(); }, []);
  useEffect(() => { if (current) setParams(Object.fromEntries(current.params.map(p => [p.name, p.default]))); setResult(null); }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  const query = () => `?${new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]))}`;
  const run = async () => {
    setBusy(true); setMessage('');
    const r = await get(`/api/response/reports/${key}${query()}`);
    setBusy(false);
    if (r.ok) setResult(r.body); else { setResult(null); setMessage(r.body.error || 'The report failed.'); }
  };
  const csv = async () => {
    const token = localStorage.getItem('dmers-token');
    const response = await fetch(`/api/response/reports/${key}${query()}&format=csv`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!response.ok) return setMessage('The CSV could not be created.');
    const url = URL.createObjectURL(await response.blob());
    const a = document.createElement('a'); a.href = url; a.download = `dmers-${key}.csv`; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  if (!catalogue.length) return <section className="dm-panel"><h2>Reports</h2><p className="dm-callout">{message || 'Loading reports…'}</p></section>;
  const bold = result?.emphasise;
  const boldIndex = bold ? result.columns.indexOf(bold.column) : -1;
  return <section className="dm-panel rs-reports">
    <div className="dm-panel-head"><p className="dm-eyebrow">Output and reports</p><h2>Reports from the incident-response database</h2>
      <p className="dm-muted">Each report is a Review II query run against live data. Important values are printed in bold, never colour only, so a black-and-white print keeps its meaning.</p></div>
    <div className="rs-inline">
      <label className="rs-field grow"><span>Report</span><select value={key} onChange={e => setKey(e.target.value)}>{catalogue.map(r => <option key={r.key} value={r.key}>{r.title}</option>)}</select></label>
      {current.params.map(p => <label className="rs-field" key={p.name}><span>{p.label}</span>
        {p.type === 'bool' ? <input type="checkbox" checked={Boolean(params[p.name])} onChange={e => setParams({ ...params, [p.name]: e.target.checked })} />
          : <input type="number" min="1" value={params[p.name] ?? ''} onChange={e => setParams({ ...params, [p.name]: e.target.value })} />}</label>)}
      <button className="dm-primary" onClick={run} disabled={busy}>{busy ? 'Running…' : 'Run report'}</button>
    </div>
    <p className="dm-muted">{current.description} <span className="rs-chip">{current.requirement}</span> <span className="rs-chip">Review II {current.review2_query}</span> <span className="rs-chip">{current.sql_feature}</span></p>
    {message && <p className="dm-callout warn">{message}</p>}
    {result && <>
      <div className="dm-row"><button className="dm-btn" onClick={csv}>Export CSV</button><button className="dm-btn" onClick={() => downloadPdf(result)}>Export PDF (black and white)</button>
        <span className="rs-muted">{result.row_count} row(s) · times in {result.time_zone}</span></div>
      <div className="dm-table-wrap"><table className="dm-table dm-dense"><thead><tr>{result.columns.map(c => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>{result.rows.map((row, i) => <tr key={i}>{row.map((v, j) => <td key={j} style={j === boldIndex && bold.values.includes(String(v)) ? { fontWeight: 900, textDecoration: 'underline' } : undefined}>{cell(v)}</td>)}</tr>)}
          {!result.rows.length && <tr><td colSpan={result.columns.length}>No rows.</td></tr>}</tbody></table></div>
      <details><summary>The SQL behind this report</summary><pre className="rs-pre">{result.sql}</pre></details>
    </>}
  </section>;
}
