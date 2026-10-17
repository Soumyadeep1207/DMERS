import React, { useCallback, useEffect, useState } from 'react';

async function api(path, options = {}) {
  const token = localStorage.getItem('dmers-token');
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}), ...options.headers },
    ...(options.body && typeof options.body !== 'string' ? { body: JSON.stringify(options.body) } : {}),
  });
  const raw = await response.text();
  let data = {};
  try { data = raw ? JSON.parse(raw) : {}; } catch { throw Error(`The service returned an unreadable response (HTTP ${response.status}).`); }
  if (!response.ok) throw Error(data.error || `Request failed (HTTP ${response.status}).`);
  return data;
}

function PortalFrame({ user, icon, title, subtitle, theme, onSignOut, children }) {
  return <main className="partner-page min-h-screen px-4 py-6 sm:px-7 sm:py-9">
    <header className="partner-header">
      <div><p className="portal-kicker">DMERS · PARTNER OPERATIONS · {user.institution || 'VERIFIED ACCESS'}</p><h1>{icon} {title}</h1><p>{subtitle}</p></div>
      <div className="partner-header-actions"><span className="partner-user">{user.name}<small>{user.email}</small></span><button className="secondary" onClick={onSignOut}>Sign out</button></div>
    </header>
    <div className={`partner-accent ${theme}`} aria-hidden="true" />
    {children}
    <footer className="partner-footer">Partner workspace · Operational updates are recorded with the signed-in organisation account.</footer>
  </main>;
}

function Stat({ label, value, hint, tone = 'cyan' }) {
  return <article className={`partner-stat ${tone}`}><span>{label}</span><b>{value}</b><small>{hint}</small></article>;
}

function Notice({ children, tone = 'info' }) {
  return children ? <p className={`partner-notice ${tone}`} role="status">{children}</p> : null;
}

function NGOPage({ user, onSignOut }) {
  const [incidents, setIncidents] = useState([]);
  const [hospitals, setHospitals] = useState([]);
  const [inventory, setInventory] = useState(() => JSON.parse(localStorage.getItem('dmers-ngo-inventory') || 'null') || { volunteers: 12, food: 160, water: 240, kits: 45, availability: 'Available for coordination' });
  const [offers, setOffers] = useState(() => JSON.parse(localStorage.getItem('dmers-ngo-offers') || '[]'));
  const [notice, setNotice] = useState('Loading the shared incident and receiving-capacity picture…');
  const [error, setError] = useState('');
  const refresh = useCallback(async () => {
    try {
      const [incidentData, hospitalData] = await Promise.all([api('/incidents'), api('/hospitals')]);
      setIncidents(incidentData.incidents || []); setHospitals(hospitalData.hospitals || []); setNotice('Shared operational picture refreshed.'); setError('');
    } catch (reason) { setError(reason.message); setNotice('Live data is unavailable. Your relief inventory remains on this device.'); }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  const saveInventory = event => { event.preventDefault(); localStorage.setItem('dmers-ngo-inventory', JSON.stringify(inventory)); setNotice('Relief capacity saved on this device. Share changes with dispatch through your verified coordination channel.'); };
  const offerSupport = incident => {
    const next = [{ id: `OFFER-${Date.now()}`, reference: incident.reference, kind: incident.disaster_type, status: 'Draft coordination offer', at: new Date().toLocaleString() }, ...offers].slice(0, 12);
    setOffers(next); localStorage.setItem('dmers-ngo-offers', JSON.stringify(next)); setNotice(`A local support offer was prepared for ${incident.reference}; contact dispatch to confirm assignment.`);
  };
  const openIncidents = incidents.filter(item => !['resolved', 'closed'].includes(String(item.status).toLowerCase()));
  const acceptingHospitals = hospitals.filter(item => item.status !== 'divert' && item.available_beds > 0);
  return <PortalFrame user={user} icon="🤝" title="NGO coordination portal" subtitle="Coordinate verified relief capacity, volunteers, and support offers with DMERS dispatch." theme="ngo" onSignOut={onSignOut}>
    <section className="partner-welcome"><div><span className="partner-eyebrow">ORGANISATION WORKSPACE</span><h2>Relief coordination overview</h2><p>Keep your deployable capacity current and review the active incident picture before offering support.</p></div><button className="secondary" onClick={refresh}>Refresh situation</button></section>
    <div className="partner-stat-grid"><Stat label="Open incidents" value={openIncidents.length} hint="Shared with authenticated partners" tone="rose"/><Stat label="Receiving hospitals" value={acceptingHospitals.length} hint="Facilities reporting available beds" tone="emerald"/><Stat label="Volunteers on roster" value={inventory.volunteers} hint="Organisation supplied count" tone="violet"/><Stat label="Relief kits" value={inventory.kits} hint="Current inventory estimate" tone="amber"/></div>
    <Notice>{error || notice}</Notice>
    <div className="partner-content-grid">
      <section className="partner-panel"><div className="partner-panel-heading"><div><span className="partner-eyebrow">NEEDS & SUPPORT</span><h2>Incident coordination board</h2></div><span className="partner-count">{openIncidents.length} active</span></div>
        {openIncidents.length ? <div className="partner-list">{openIncidents.map(item => <article className="partner-record" key={item.id}><div className="partner-record-top"><b>{item.reference}</b><span className={`partner-badge ${String(item.severity).toLowerCase()}`}>{item.severity}</span></div><h3>{item.disaster_type}</h3><p>{item.location} · {item.status}</p><button className="secondary" onClick={() => offerSupport(item)}>Prepare support offer</button></article>)}</div> : <p className="partner-empty">No active incident records are available.</p>}
      </section>
      <div className="partner-stack">
        <section className="partner-panel"><div className="partner-panel-heading"><div><span className="partner-eyebrow">DEPLOYABLE RESOURCES</span><h2>Relief capacity</h2></div><span>📦</span></div>
          <form className="partner-form" onSubmit={saveInventory}><label>Volunteers<input type="number" min="0" value={inventory.volunteers} onChange={e => setInventory({ ...inventory, volunteers: Number(e.target.value) })}/></label><label>Food packs<input type="number" min="0" value={inventory.food} onChange={e => setInventory({ ...inventory, food: Number(e.target.value) })}/></label><label>Water units<input type="number" min="0" value={inventory.water} onChange={e => setInventory({ ...inventory, water: Number(e.target.value) })}/></label><label>Relief kits<input type="number" min="0" value={inventory.kits} onChange={e => setInventory({ ...inventory, kits: Number(e.target.value) })}/></label><label className="wide">Availability<select value={inventory.availability} onChange={e => setInventory({ ...inventory, availability: e.target.value })}><option>Available for coordination</option><option>Limited availability</option><option>Currently deployed</option></select></label><button className="primary wide">Save organisation capacity</button><small className="wide">Capacity is saved locally in this demo and is not yet a shared server resource record.</small></form>
        </section>
        <section className="partner-panel"><div className="partner-panel-heading"><div><span className="partner-eyebrow">RECEIVING NETWORK</span><h2>Hospital capacity</h2></div><span>🏥</span></div><div className="partner-list compact">{acceptingHospitals.slice(0, 5).map(item => <article className="partner-record" key={item.id}><div className="partner-record-top"><b>{item.name}</b><span className="partner-badge ok">{item.available_beds} beds</span></div><p>{item.location || 'Location not recorded'} · {item.status}</p></article>)}{!acceptingHospitals.length && <p className="partner-empty">No receiving capacity is currently reported.</p>}</div></section>
      </div>
    </div>
    <section className="partner-panel"><div className="partner-panel-heading"><div><span className="partner-eyebrow">LOCAL OFFER LOG</span><h2>Prepared support offers</h2></div><span>{offers.length} saved</span></div>{offers.length ? <div className="partner-list compact">{offers.map(item => <article className="partner-record" key={item.id}><div className="partner-record-top"><b>{item.reference} · {item.kind}</b><span className="partner-badge pending">{item.status}</span></div><p>{item.at} · Confirm through the dispatch portal before deploying.</p></article>)}</div> : <p className="partner-empty">Preparing an offer records your local intent. Dispatch confirmation is still required before deployment.</p>}</section>
  </PortalFrame>;
}

function DispatchPage({ user, onSignOut }) {
  const [incidents, setIncidents] = useState([]); const [hospitals, setHospitals] = useState([]); const [teams, setTeams] = useState([]); const [missions, setMissions] = useState([]);
  const [assignment, setAssignment] = useState({ reportId: '', team: '', hospitalId: '' }); const [notice, setNotice] = useState('Loading dispatch queue…'); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const refresh = useCallback(async () => {
    try {
      const [incidentData, hospitalData, teamData, relationshipData] = await Promise.all([api('/incidents'), api('/hospitals'), api('/data/tables'), api('/data/relationships')]);
      const active = (incidentData.incidents || []).filter(item => !['resolved', 'closed'].includes(String(item.status).toLowerCase()));
      setIncidents(active); setHospitals(hospitalData.hospitals || []); setTeams(teamData.teams || []); setMissions(relationshipData.missions || []);
      setAssignment(previous => ({ reportId: active.some(item => item.reference === previous.reportId) ? previous.reportId : (active[0]?.reference || ''), team: (teamData.teams || []).some(item => item.name === previous.team && item.availability === 'available') ? previous.team : ((teamData.teams || []).find(item => item.availability === 'available')?.name || ''), hospitalId: previous.hospitalId || String((hospitalData.hospitals || []).find(item => item.status !== 'divert' && item.available_beds > 0)?.id || '') }));
      setNotice('Live dispatch queue and receiving capacity loaded.'); setError('');
    } catch (reason) { setError(reason.message); setNotice('Dispatch data could not be loaded. Check the backend connection.'); }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  const assign = async event => {
    event.preventDefault(); setBusy(true);
    try { await api('/missions/claim', { method: 'POST', body: { reportId: assignment.reportId, team: assignment.team, hospitalId: Number(assignment.hospitalId) || null } }); setNotice(`Mission created for ${assignment.reportId}; ${assignment.team} assigned.`); setError(''); await refresh(); }
    catch (reason) { setError(reason.message); } finally { setBusy(false); }
  };
  const advance = async mission => {
    const steps = ['assigned', 'acknowledged', 'en_route', 'on_scene', 'in_progress', 'at_hospital', 'completed'];
    const next = steps[Math.min(steps.indexOf(mission.mission_status) + 1, steps.length - 1)];
    try { await api(`/missions/${mission.mission_id}/status`, { method: 'POST', body: { status: next } }); setNotice(`${mission.incident_reference || 'Mission'} updated to ${next.replaceAll('_', ' ')}.`); await refresh(); }
    catch (reason) { setError(reason.message); }
  };
  const activeMissions = missions.filter(item => !['completed', 'aborted'].includes(item.mission_status));
  return <PortalFrame user={user} icon="🚨" title="Service dispatch operations" subtitle="Review the active incident queue, assign a response team, select a receiving hospital, and follow mission progress." theme="dispatch" onSignOut={onSignOut}>
    <section className="partner-welcome"><div><span className="partner-eyebrow">DISPATCH DESK · LIVE QUEUE</span><h2>Response coordination</h2><p>Assignments are persisted to DMERS with linked incident, team, hospital, and audit records.</p></div><button className="secondary" onClick={refresh}>Refresh queue</button></section>
    <div className="partner-stat-grid"><Stat label="Open incidents" value={incidents.length} hint="Reported, verified, or dispatched" tone="rose"/><Stat label="Active missions" value={activeMissions.length} hint="Not completed or aborted" tone="cyan"/><Stat label="Available teams" value={teams.filter(item => item.availability === 'available').length} hint="Can be assigned now" tone="emerald"/><Stat label="Receiving hospitals" value={hospitals.filter(item => item.status !== 'divert' && item.available_beds > 0).length} hint="Capacity currently reported" tone="violet"/></div>
    <Notice tone={error ? 'error' : 'info'}>{error || notice}</Notice>
    <div className="partner-content-grid dispatch-grid">
      <section className="partner-panel"><div className="partner-panel-heading"><div><span className="partner-eyebrow">ASSIGN RESPONSE</span><h2>New mission</h2></div><span>➜</span></div><form className="partner-form" onSubmit={assign}><label className="wide">Incident<select required value={assignment.reportId} onChange={e => setAssignment({ ...assignment, reportId: e.target.value })}><option value="">Select an incident</option>{incidents.map(item => <option key={item.id} value={item.reference}>{item.reference} · {item.disaster_type} · {item.severity}</option>)}</select></label><label>Response team<select required value={assignment.team} onChange={e => setAssignment({ ...assignment, team: e.target.value })}><option value="">Select an available team</option>{teams.filter(item => item.availability === 'available').map(item => <option key={item.id}>{item.name}</option>)}</select></label><label>Receiving hospital<select required value={assignment.hospitalId} onChange={e => setAssignment({ ...assignment, hospitalId: e.target.value })}><option value="">Select receiving hospital</option>{hospitals.filter(item => item.status !== 'divert' && item.available_beds > 0).map(item => <option value={item.id} key={item.id}>{item.name} · {item.available_beds} beds</option>)}</select></label><button className="primary wide" disabled={busy || !incidents.length || !assignment.team}>{busy ? 'Saving mission…' : 'Assign team and receiving hospital'}</button><small className="wide">If the incident already has an active mission, the database will reject a duplicate assignment.</small></form></section>
      <section className="partner-panel"><div className="partner-panel-heading"><div><span className="partner-eyebrow">INCIDENT QUEUE</span><h2>Active incidents</h2></div><span className="partner-count">{incidents.length}</span></div><div className="partner-list">{incidents.map(item => <article className="partner-record" key={item.id}><div className="partner-record-top"><b>{item.reference}</b><span className={`partner-badge ${String(item.severity).toLowerCase()}`}>{item.severity}</span></div><h3>{item.disaster_type}</h3><p>{item.location} · {item.status}</p><p className="partner-description">{item.description}</p></article>)}{!incidents.length && <p className="partner-empty">No active incidents are in the queue.</p>}</div></section>
    </div>
    <section className="partner-panel"><div className="partner-panel-heading"><div><span className="partner-eyebrow">MISSION CONTROL</span><h2>Assigned response missions</h2></div><span>{activeMissions.length} active</span></div><div className="partner-list mission-list">{activeMissions.map(item => <article className="partner-record mission-record" key={item.mission_id}><div className="partner-record-top"><b>Mission {item.mission_id} · {item.incident_reference || 'Legacy report'}</b><span className="partner-badge pending">{item.mission_status.replaceAll('_', ' ')}</span></div><p>{item.disaster_type || 'Response task'} · {item.incident_location || 'Location pending'}</p><p>Team: <b>{item.team_name || 'Not assigned'}</b> · Hospital: <b>{item.hospital_name || 'Not assigned'}</b></p><button className="secondary" disabled={item.mission_status === 'completed'} onClick={() => advance(item)}>Advance mission status</button></article>)}{!activeMissions.length && <p className="partner-empty">No active missions yet.</p>}</div></section>
  </PortalFrame>;
}

function HospitalPage({ user, onSignOut }) {
  const [hospital, setHospital] = useState(null); const [transfers, setTransfers] = useState([]); const [notice, setNotice] = useState('Loading facility information…'); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const refresh = useCallback(async () => {
    try {
      const [hospitalData, transferData] = await Promise.all([api('/hospitals'), api(`/hospitals/${user.hospital_id}/transfers`)]);
      const record = (hospitalData.hospitals || []).find(item => Number(item.id) === Number(user.hospital_id));
      setHospital(record || null);
      setTransfers((transferData.transfers || []).filter(item => !['completed', 'aborted'].includes(item.mission_status)));
      setNotice(record ? 'Facility record and assigned transfers are up to date.' : 'This account is not linked to a hospital facility. Contact a DMERS administrator.'); setError('');
    } catch (reason) { setError(reason.message); setNotice('Hospital information could not be loaded.'); }
  }, [user.hospital_id]);
  useEffect(() => { refresh(); }, [refresh]);
  const save = async event => {
    event.preventDefault(); if (!hospital) return; setBusy(true);
    try { const result = await api(`/hospitals/${hospital.id}/capacity`, { method: 'PATCH', body: { total_beds: Number(hospital.total_beds), available_beds: Number(hospital.available_beds), status: hospital.status } }); setHospital(result.hospital); setNotice('Hospital capacity saved to the shared DMERS database.'); setError(''); }
    catch (reason) { setError(reason.message); } finally { setBusy(false); }
  };
  const receive = async mission => {
    try { await api(`/hospitals/missions/${mission.mission_id}/receive`, { method: 'POST', body: {} }); setNotice(`${mission.incident_reference || `Mission ${mission.mission_id}`} marked as received at your facility.`); await refresh(); }
    catch (reason) { setError(reason.message); }
  };
  const received = transfers.filter(item => item.mission_status === 'at_hospital').length;
  const inbound = transfers.filter(item => item.mission_status !== 'at_hospital');
  return <PortalFrame user={user} icon="🏥" title="Hospital management" subtitle="Publish receiving capacity, review inbound DMERS transfers, and acknowledge arrivals for your facility." theme="hospital" onSignOut={onSignOut}>
    <section className="partner-welcome"><div><span className="partner-eyebrow">FACILITY OPERATIONS</span><h2>{hospital?.name || user.institution}</h2><p>Capacity changes and transfer receipts are linked to this hospital account and written to the shared database.</p></div><button className="secondary" onClick={refresh}>Refresh facility data</button></section>
    <div className="partner-stat-grid"><Stat label="Total beds" value={hospital?.total_beds ?? '—'} hint="Configured facility capacity" tone="cyan"/><Stat label="Beds available" value={hospital?.available_beds ?? '—'} hint="Current receiving estimate" tone="emerald"/><Stat label="Inbound transfers" value={inbound.length} hint="Assigned to this facility" tone="amber"/><Stat label="Arrived" value={received} hint="Acknowledged at hospital" tone="violet"/></div>
    <Notice tone={error ? 'error' : 'info'}>{error || notice}</Notice>
    <div className="partner-content-grid hospital-grid">
      <section className="partner-panel"><div className="partner-panel-heading"><div><span className="partner-eyebrow">CAPACITY PUBLISHING</span><h2>Receiving status</h2></div><span>🛏️</span></div>{hospital ? <form className="partner-form" onSubmit={save}><label>Total beds<input type="number" min="0" value={hospital.total_beds} onChange={e => setHospital({ ...hospital, total_beds: Number(e.target.value), available_beds: Math.min(Number(hospital.available_beds), Number(e.target.value)) })}/></label><label>Available beds<input type="number" min="0" max={hospital.total_beds} value={hospital.available_beds} onChange={e => setHospital({ ...hospital, available_beds: Number(e.target.value) })}/></label><label className="wide">Reception status<select value={hospital.status} onChange={e => setHospital({ ...hospital, status: e.target.value })}><option value="accepting">Accepting transfers</option><option value="limited">Limited capacity</option><option value="divert">Divert incoming cases</option></select></label><button className="primary wide" disabled={busy}>{busy ? 'Publishing…' : 'Publish facility capacity'}</button><small className="wide">Available beds cannot exceed the facility's total bed count.</small></form> : <p className="partner-empty">No hospital is linked to this account. Ask an administrator to provision a hospital-specific login.</p>}</section>
      <section className="partner-panel"><div className="partner-panel-heading"><div><span className="partner-eyebrow">TRANSFER HANDOFF</span><h2>Inbound patients</h2></div><span>{inbound.length} pending</span></div><div className="partner-list">{transfers.map(item => <article className="partner-record" key={item.mission_id}><div className="partner-record-top"><b>{item.incident_reference || `Mission ${item.mission_id}`}</b><span className={`partner-badge ${item.mission_status === 'at_hospital' ? 'ok' : 'pending'}`}>{item.mission_status.replaceAll('_', ' ')}</span></div><h3>{item.disaster_type || 'Emergency transfer'}</h3><p>{item.incident_location || 'Location pending'} · Team {item.team_name || 'not assigned'}</p>{item.mission_status !== 'at_hospital' && <button className="secondary" onClick={() => receive(item)}>Confirm arrival at this hospital</button>}</article>)}{!transfers.length && <p className="partner-empty">No transfers have been routed to this facility.</p>}</div></section>
    </div>
    <p className="partner-privacy-note">This workspace shows incident references and operational transfer details only. Do not enter patient names or sensitive clinical information in incident notes.</p>
  </PortalFrame>;
}

export function PartnerPortal({ user, onSignOut }) {
  if (user.portal === 'ngo') return <NGOPage user={user} onSignOut={onSignOut}/>;
  if (user.portal === 'dispatch') return <DispatchPage user={user} onSignOut={onSignOut}/>;
  if (user.portal === 'hospital') return <HospitalPage user={user} onSignOut={onSignOut}/>;
  return null;
}

export function PartnerAccountProvisioner({ user }) {
  const [hospitals, setHospitals] = useState([]);
  const [form, setForm] = useState({ name: '', email: '', password: '', portal: 'ngo', institution: '', hospital_id: '' });
  const [notice, setNotice] = useState(''); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  useEffect(() => { api('/hospitals').then(data => setHospitals(data.hospitals || [])).catch(() => setHospitals([])); }, []);
  const submit = async event => {
    event.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      const result = await api('/admin/partner-accounts', { method: 'POST', body: { ...form, hospital_id: form.portal === 'hospital' ? Number(form.hospital_id) : null } });
      setNotice(`${result.user.portal.toUpperCase()} login created for ${result.user.email}. Send its credentials through your organisation's approved channel.`);
      setForm({ name: '', email: '', password: '', portal: form.portal, institution: '', hospital_id: form.hospital_id });
    } catch (reason) { setError(reason.message); } finally { setBusy(false); }
  };
  if (user?.role !== 'admin') return null;
  return <div className="partner-provisioner"><div><span className="partner-eyebrow">ADMIN ONLY · VERIFIED PARTNER ACCESS</span><h3>Create a partner portal login</h3><p>Accounts are provisioned by an administrator; NGO, dispatch, and hospital access cannot be self-registered.</p></div>
    <form className="partner-form" onSubmit={submit}><label>Portal<select value={form.portal} onChange={e => setForm({ ...form, portal: e.target.value })}><option value="ngo">NGO coordination</option><option value="dispatch">Service dispatch</option><option value="hospital">Hospital management</option></select></label><label>Organisation / facility<input required value={form.institution} onChange={e => setForm({ ...form, institution: e.target.value })} placeholder="Verified organisation name"/></label><label>Account holder<input required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })}/></label><label>Login email<input required type="email" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })}/></label><label>Temporary password<input required minLength="10" type="password" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })}/></label>{form.portal === 'hospital' && <label>Managed hospital<select required value={form.hospital_id} onChange={e => setForm({ ...form, hospital_id: e.target.value })}><option value="">Select facility</option>{hospitals.map(item => <option value={item.id} key={item.id}>{item.name} · {item.location || 'location not recorded'}</option>)}</select></label>}<button className="primary wide" disabled={busy}>{busy ? 'Creating login…' : 'Create partner login'}</button></form>
    <Notice tone={error ? 'error' : 'success'}>{error || notice}</Notice>
  </div>;
}
