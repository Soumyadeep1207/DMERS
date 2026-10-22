import React, { useState } from 'react';

export const isAdministrator = () => { try { return JSON.parse(localStorage.getItem('dmers-user') || 'null')?.role === 'admin'; } catch { return false; } };

export function Section({ eyebrow, title, why, children }) {
  return <section className="dm-panel lab-section">
    <div className="dm-panel-head"><p className="dm-eyebrow">{eyebrow}</p><h2>{title}</h2>{why && <p className="dm-muted">{why}</p>}</div>
    {children}
  </section>;
}

export const Notice = ({ tone = '', children }) => (children ? <p className={`rs-notice ${tone}`}>{children}</p> : null);
export const Chip = ({ tone = '', children }) => <span className={`rs-chip ${tone}`}>{children}</span>;
export const Field = ({ label, children, grow }) => <label className={`rs-field${grow ? ' grow' : ''}`}><span>{label}</span>{children}</label>;

/** `const [busy, guard] = useBusy(); onClick={guard(async () => ...)}` keeps a button disabled while its request runs. */
export function useBusy() {
  const [busy, setBusy] = useState(false);
  const guard = fn => async (...args) => { setBusy(true); try { return await fn(...args); } finally { setBusy(false); } };
  return [busy, guard];
}

export const message = response => response.body?.error || (response.status === 403 ? 'Your account type cannot use this tool.' : 'The request failed.');

export const Table = ({ columns, rows, empty = 'No rows.' }) => <div className="dm-table-wrap"><table className="dm-table dm-dense">
  <thead><tr>{columns.map(c => <th key={c}>{c}</th>)}</tr></thead>
  <tbody>{rows.map((row, i) => <tr key={i}>{row.map((v, j) => <td key={j}>{v === null || v === undefined ? '—' : v}</td>)}</tr>)}
    {!rows.length && <tr><td colSpan={columns.length}>{empty}</td></tr>}</tbody></table></div>;

export const time = value => (value ? new Date(value).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' }) : '—');
