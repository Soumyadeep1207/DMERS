import React from 'react';
import RiskBreakdown from './RiskBreakdown.jsx';
import { ALGORITHM_COLOR } from './mapLayers.js';

const fmtKm = meters => (Math.abs(meters) < 1000 ? `${Math.round(meters)} m` : `${(meters / 1000).toFixed(2)} km`);
const fmtMin = seconds => `${Math.max(1, Math.round(seconds / 60))} min`;
const ALGORITHM_LABEL = { bfs: 'BFS', dfs: 'DFS', ucs: 'Uniform cost', greedy: 'Greedy best-first', astar: 'A*' };

function ClosureSummary({ closures }) {
  if (!closures?.length) return null;
  const groups = new Map();
  closures.forEach(shape => { const key = `${shape.road}|${shape.cause}`; groups.set(key, (groups.get(key) || 0) + 1); });
  return <div className="dm-block"><h4>Closed roads <span className="dm-count">{closures.length} segments</span></h4>
    <ul className="dm-list">{[...groups].map(([key, count]) => { const [road, cause] = key.split('|'); return <li key={key}><i className="dm-dot danger"/><span><b>{road}</b> · {count} segment{count > 1 ? 's' : ''} closed<small>Caused by: {cause}. The planner treats these as impassable in every algorithm.</small></span></li>; })}</ul></div>;
}

function Comparison({ data, busy, onCompare, onSelect, selected }) {
  return <div className="dm-block"><div className="dm-block-head"><h4>Algorithm comparison on real roads</h4><button className="dm-btn small" onClick={onCompare} disabled={busy}>{busy ? 'Running…' : data ? 'Re-run' : 'Compare all five'}</button></div>
    {!data && <p className="dm-muted">Runs BFS, DFS, UCS, Greedy and A* on the same road query, closures and weather, then reports time, risk and how far each is from the optimum.</p>}
    {data && <><div className="dm-table-wrap"><table className="dm-table"><thead><tr><th>Algorithm</th><th>Distance</th><th>ETA</th><th>Risk</th><th>Nodes</th><th>Gap</th></tr></thead><tbody>{Object.entries(data.results).map(([name, row]) => <tr key={name} className={selected === name ? 'active' : ''} onClick={() => row.found && onSelect(name)}>
      <td><i className="dm-swatch" style={{ background: ALGORITHM_COLOR[name] }}/>{ALGORITHM_LABEL[name]}</td>
      {row.found ? <><td>{fmtKm(row.distance_m)}</td><td>{fmtMin(row.eta_s)}</td><td><span className={`dm-pill ${row.risk_band.toLowerCase()}`}>{row.risk_score}</span></td><td>{row.nodes_explored.toLocaleString()}</td><td>{row.optimality_gap_pct === 0 ? 'optimal' : `+${row.optimality_gap_pct}%`}</td></> : <td colSpan="5">No route</td>}
    </tr>)}</tbody></table></div>
      <p className="dm-muted">{data.reading_guide} Click a row to draw that path and its explored nodes. {data.closed_segments ? `${data.closed_segments} closed segments applied.` : ''}</p></>}
  </div>;
}

export default function RoutePanel({ info, comparison, comparing, onCompare, onSelectAlgorithm, selectedAlgorithm }) {
  if (!info) return <div className="dm-empty"><b>No route yet</b><p>Place a rescue team, at least one victim and a receiving hospital, add any hazards or road blocks, then press <em>Plan rescue route</em>. The planner routes on real Vellore streets and reports risk for every figure.</p></div>;
  const far = (info.snapped || []).filter(item => item.snap_distance_m > 120);
  return <div className="dm-route-panel">
    <div className="dm-kpis">
      <div><span>Distance</span><b>{fmtKm(info.distanceMeters)}</b></div>
      <div><span>Estimated time</span><b>{fmtMin(info.durationSeconds)}</b></div>
      <div className={`dm-kpi-risk dm-band-${info.risk.band.toLowerCase()}`}><span>Route risk</span><b>{info.risk.score}<small>/100</small></b></div>
      <div><span>Added by hazards</span><b>{info.detour ? `+${fmtKm(Math.max(0, info.detour.extra_distance_m))}` : 'none'}</b></div>
    </div>
    {info.detour && <p className="dm-callout warn">Without any hazards this trip would be <b>{fmtKm(info.detour.baseline_distance_m)}</b> and <b>{fmtMin(info.detour.baseline_eta_s)}</b> (grey dashed line). Hazards{info.detour.closed_segments ? ` and ${info.detour.closed_segments} closed segment${info.detour.closed_segments > 1 ? 's' : ''}` : ''} add <b>{fmtKm(Math.max(0, info.detour.extra_distance_m))}</b> and <b>{Math.max(0, Math.round(info.detour.extra_time_s))} s</b>.</p>}
    {far.length > 0 && <p className="dm-callout">{far.length} marker{far.length > 1 ? 's are' : ' is'} more than 120 m from a mapped road (up to {Math.round(Math.max(...far.map(item => item.snap_distance_m)))} m). Routing starts from the nearest road point.</p>}
    <RiskBreakdown risk={info.risk} title="Route risk"/>
    {info.plan && <div className="dm-block"><h4>Rescue sequence <span className="dm-count">{info.plan.method}</span></h4><ol className="dm-steps">{info.plan.assignments.map(item => <li key={item.victim}><b>Victim {item.victim}</b> → {item.hospital}<small>Hospital chosen by routed {info.plan.cost_basis}, not straight-line distance.</small></li>)}</ol>
      {info.plan.unreachable_victims.length > 0 && <p className="dm-callout warn">Victim {info.plan.unreachable_victims.join(', ')} cannot be reached with the current closures.</p>}</div>}
    <ClosureSummary closures={info.closures}/>
    <div className="dm-block"><h4>Route follows</h4><ul className="dm-list roads">{info.roads.slice(0, 14).map((road, index) => <li key={index}><i className="dm-dot"/><span><b>{road.road}</b><small>{road.class} · {road.length_m} m</small></span></li>)}</ul>{info.roads.length > 14 && <p className="dm-muted">+{info.roads.length - 14} more road changes</p>}</div>
    <details className="dm-block"><summary>Situation risk at this scene</summary><RiskBreakdown risk={info.situation} title="Situation risk" compact/></details>
    <Comparison data={comparison} busy={comparing} onCompare={onCompare} onSelect={onSelectAlgorithm} selected={selectedAlgorithm}/>
    <p className="dm-attrib">Roads © OpenStreetMap contributors (ODbL). Travel times are planning estimates from road class and weather, not live traffic.</p>
  </div>;
}
