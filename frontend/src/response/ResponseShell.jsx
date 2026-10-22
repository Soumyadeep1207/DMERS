import React, { useState } from 'react';
import ActivityPanel from './ActivityPanel.jsx';
import ResponseOps from './ResponseOps.jsx';
import Reports from './Reports.jsx';
import DemoMode from './DemoMode.jsx';
import AdminPanel from './AdminPanel.jsx';
import DatabaseLab from './DatabaseLab.jsx';

const TABS = [['ops', 'Operations'], ['reports', 'Reports'], ['admin', 'Administration'], ['lab', 'Database lab'], ['demo', 'Guided demo']];
const isAdministrator = () => { try { return JSON.parse(localStorage.getItem('dmers-user') || 'null')?.role === 'admin'; } catch { return false; } };

/** The incident-response workspace: transactions, reports and the guided demonstration, plus the activity drawer. */
export default function ResponseShell({ initial = 'ops' }) {
  const [tab, setTab] = useState(initial);
  return <div className="rs-shell">
    <div className="rs-tabs" role="tablist" aria-label="Incident response">{TABS.filter(([id]) => id !== 'admin' || isAdministrator()).map(([id, label]) => <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>{label}</button>)}</div>
    {tab === 'ops' && <ResponseOps />}
    {tab === 'reports' && <Reports />}
    {tab === 'admin' && <AdminPanel />}
    {tab === 'lab' && <DatabaseLab />}
    {tab === 'demo' && <DemoMode />}
    <ActivityPanel />
  </div>;
}
