import React, { useState } from 'react';
import ChainLab from './lab/ChainLab.jsx';
import AccessLab from './lab/AccessLab.jsx';
import IsolationLab from './lab/IsolationLab.jsx';
import BookingLab from './lab/BookingLab.jsx';
import RoutingLab from './lab/RoutingLab.jsx';
import OptimiserLab from './lab/OptimiserLab.jsx';
import LiveFeed from './lab/LiveFeed.jsx';
import AnalyticsLab from './lab/AnalyticsLab.jsx';
import PrivacyLab from './lab/PrivacyLab.jsx';

const LABS = [['chain', '1 Integrity', ChainLab], ['access', '2 Access control', AccessLab], ['isolation', '3 Isolation', IsolationLab], ['booking', '4 Reservations', BookingLab],
  ['routing', '5 Routing', RoutingLab], ['optimiser', '6 Query optimiser', OptimiserLab], ['live', '7 Live push', LiveFeed], ['analytics', '8 Analytics', AnalyticsLab], ['privacy', '9 Privacy', PrivacyLab]];

/** What PostgreSQL does for DMERS beyond storing rows: nine laboratories, each running against the real database. */
export default function DatabaseLab() {
  const [lab, setLab] = useState('chain');
  const Current = LABS.find(l => l[0] === lab)[2];
  return <div className="rs-admin">
    <div className="rs-tabs lab-tabs" role="tablist" aria-label="Database laboratories">{LABS.map(([id, label]) => <button key={id} role="tab" aria-selected={lab === id} className={lab === id ? 'active' : ''} onClick={() => setLab(id)}>{label}</button>)}</div>
    <Current key={lab} />
  </div>;
}
