import React, { useEffect, useState } from 'react';
import { Chip, Notice, Section } from './labUi.jsx';
import { connectLive } from './live.js';
import { describeEvent } from './labLogic.js';

/** Idea 7: LISTEN/NOTIFY. PostgreSQL pushes committed changes; no screen polls. */
export default function LiveFeed() {
  const [state, setState] = useState('connecting');
  const [events, setEvents] = useState([]);
  useEffect(() => connectLive(event => setEvents(prev => [{ ...event, at: new Date() }, ...prev].slice(0, 40)), setState), []);
  const tone = state === 'live' ? 'ok' : state === 'forbidden' ? 'bad' : 'warn';
  return <Section eyebrow="Database lab 7 · LISTEN / NOTIFY" title="Live push from PostgreSQL"
    why="Triggers on incidents and dispatches call pg_notify. PostgreSQL delivers the message only when the transaction COMMITS and drops it on rollback, so this feed can never show a change that did not happen. The server turns the channel into a server-sent-event stream; the browser does not poll.">
    <div className="rs-inline"><Chip tone={tone}>{state === 'live' ? 'connected: listening on dmers_events' : state}</Chip><span className="rs-muted">Open Operations in a second window, verify an incident or dispatch a unit, and watch it arrive here.</span></div>
    {state === 'forbidden' && <Notice tone="bad">Live updates are for coordinators, unit leads and administrators.</Notice>}
    <ul className="rs-rows">{events.map((e, i) => <li key={i} className="rs-notice">{e.at.toLocaleTimeString('en-IN')} · <strong>{describeEvent(e)}</strong></li>)}
      {!events.length && <li className="rs-muted">Nothing yet. Messages contain ids and statuses only, never names or descriptions.</li>}</ul>
  </Section>;
}
