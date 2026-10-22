import React, { useState } from 'react';
import ActivityPanel from './ActivityPanel.jsx';
import ResponseOps from './ResponseOps.jsx';
import Reports from './Reports.jsx';
import DemoMode from './DemoMode.jsx';

const TABS = [['ops', 'Operations'], ['reports', 'Reports'], ['demo', 'Guided demo']];

/** The incident-response workspace: transactions, reports and the guided demonstration, plus the activity drawer. */
export default function ResponseShell({ initial = 'ops' }) {
  const [tab, setTab] = useState(initial);
  return <div className="rs-shell">
    <div className="rs-tabs" role="tablist" aria-label="Incident response">{TABS.map(([id, label]) => <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>{label}</button>)}</div>
    {tab === 'ops' && <ResponseOps />}
    {tab === 'reports' && <Reports />}
    {tab === 'demo' && <DemoMode />}
    <ActivityPanel />
  </div>;
}
