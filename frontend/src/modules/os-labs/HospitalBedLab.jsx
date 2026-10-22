import { useState } from 'react';
import RiskBreakdown, { RiskGauge } from '../../RiskBreakdown.jsx';
import { evaluateBankerRequest, bankerSafeSequence } from '../../osAlgorithms.js';

export const BED_DEFAULTS = {
  icuBeds: 8, wardBeds: 40, icuBoarding: 2, wardBoarding: 10, icuStayHours: 48, wardStayHours: 12,
  icuArrivalsPerHour: 0.12, urgentArrivalsPerHour: 1.2, minorArrivalsPerHour: 1.6, icuOccupied: 5, wardOccupied: 30,
  surgeMultiplier: 3, surgeHours: 12,
};
const PRESETS = {
  'Normal day': BED_DEFAULTS,
  'Monsoon flooding': { ...BED_DEFAULTS, surgeMultiplier: 2.2, surgeHours: 18, wardOccupied: 34, minorArrivalsPerHour: 2.0 },
  'Mass-casualty event': { ...BED_DEFAULTS, surgeMultiplier: 4, surgeHours: 8, icuOccupied: 6, wardOccupied: 36 },
};
const FIELDS = [
  ['icuBeds', 'ICU beds', 'beds'], ['icuBoarding', 'ICU boarding places', 'places'], ['icuStayHours', 'Mean ICU stay', 'hours'], ['icuArrivalsPerHour', 'Critical arrivals', 'per hour'], ['icuOccupied', 'ICU beds occupied now', 'beds'],
  ['wardBeds', 'Ward beds', 'beds'], ['wardBoarding', 'ED boarding places', 'places'], ['wardStayHours', 'Mean ward stay', 'hours'], ['urgentArrivalsPerHour', 'Urgent arrivals', 'per hour'], ['minorArrivalsPerHour', 'Minor arrivals', 'per hour'], ['wardOccupied', 'Ward beds occupied now', 'beds'],
  ['surgeMultiplier', 'Surge multiplier', '× arrivals'], ['surgeHours', 'Surge duration', 'hours'],
];
const pct = value => `${(value * 100).toFixed(1)}%`;
const hours = value => (Number.isFinite(value) ? `${value.toFixed(2)} h` : 'unbounded');
const minutes = value => (!Number.isFinite(value) ? 'unbounded' : value >= 120 ? `${(value / 60).toFixed(1)} h` : `${value.toFixed(1)} min`);

export function BedControls({ inputs, setInputs }) {
  return <div className="sm:col-span-2 lg:col-span-4 space-y-3">
    <div className="flex flex-wrap items-center gap-2"><span className="text-xs font-bold">Scenarios:</span>{Object.keys(PRESETS).map(name => <button key={name} className="rounded-full bg-slate-100 px-3 py-1 text-xs hover:bg-indigo-100" onClick={() => setInputs(value => ({ ...value, ...PRESETS[name] }))}>{name}</button>)}</div>
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{FIELDS.map(([key, label, unit]) => <label key={key}>{label} <small className="font-normal opacity-70">({unit})</small><input type="number" min="0" step="any" value={inputs[key]} onChange={event => setInputs(value => ({ ...value, [key]: Number(event.target.value) }))}/></label>)}</div>
    <p className="text-xs opacity-80">Arrival rates and stays describe <b>this</b> hospital; the defaults are illustrative, not measured. Beds = a counting semaphore; patients beyond beds + boarding places are diverted.</p>
  </div>;
}

function Trajectory({ fluid, beds, label }) {
  const points = fluid.trajectory, peak = Math.max(beds * 1.15, ...points.map(point => point.occupied)), width = 240, height = 70;
  const x = hour => (hour / Math.max(1, points.length - 1)) * width, y = value => height - (value / peak) * height;
  const path = points.map((point, index) => `${index ? 'L' : 'M'}${x(point.hour).toFixed(1)} ${y(point.occupied).toFixed(1)}`).join(' ');
  return <figure className="dm-spark"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${label} expected occupancy over the surge`}><line x1="0" x2={width} y1={y(beds)} y2={y(beds)} className="cap"/><path d={path}/></svg><figcaption>{label}: demand would need <b>{fluid.steadyDemandBeds.toFixed(1)}</b> beds{fluid.hoursToFull === 0 ? '; already full' : fluid.hoursToFull ? `; full in about ${fluid.hoursToFull.toFixed(1)} h` : '; stays within capacity'}</figcaption></figure>;
}

function PoolCard({ title, beds, pool, extra }) {
  const sim = pool.simulated;
  const rows = [
    ['Offered load', `${pool.offeredLoad.toFixed(2)} beds`, 'a = λ / μ'],
    ['Bed utilisation', pct(pool.utilisation), 'λ_eff / (c μ)'],
    ['All beds busy', pct(pool.pAllBedsBusy), 'P(n ≥ c)'],
    ['Admitted patient must wait', pct(pool.pWait), 'PASTA'],
    ['Diverted (exact)', pct(pool.blocking), `Erlang-B no-queue bound ${pct(pool.erlangB)}`],
    ['Diverted (simulated)', `${pct(sim.divertedFraction)} ± ${pct(sim.divertedHalfWidth95)}`, `${sim.replications} seeded runs`],
    ['Mean boarding wait', hours(pool.meanWaitHours), 'L_q / λ_eff'],
    ['Expected free beds', pool.freeBedsExpected.toFixed(1), 'c − busy'],
    ['Beds for ≤1% diversion', pool.bedsNeededForOnePercent ?? '>2000', `now ${beds}`],
  ];
  return <article className="dm-pool"><header><RiskGauge score={pool.risk.score} band={pool.risk.band} size={96}/><div><p className="dm-eyebrow">{title}</p><h4>{beds} beds · {pct(pool.utilisation)} busy</h4><p className="dm-muted">{pool.risk.guidance}</p></div></header>
    <table className="dm-table dm-dense"><tbody>{rows.map(([label, value, note]) => <tr key={label}><td>{label}</td><td><b>{value}</b></td><td className="dm-muted">{note}</td></tr>)}</tbody></table>{extra}</article>;
}

function AdmissionBanker() {
  const labels = ['Resource A: ICU bed', 'B: Ventilator', 'C: Specialist nurse'];
  const maximum = [[2, 1, 2], [1, 1, 1], [2, 1, 2], [1, 0, 1]], start = [[1, 0, 1], [0, 1, 0], [1, 0, 1], [0, 0, 1]], free = [1, 1, 1];
  const [allocation, setAllocation] = useState(start), [available, setAvailable] = useState(free), [patient, setPatient] = useState(1), [request, setRequest] = useState([1, 0, 1]), [message, setMessage] = useState('');
  const safe = bankerSafeSequence(available, allocation, maximum);
  const evaluate = () => { const result = evaluateBankerRequest(available, allocation, maximum, Number(patient), request); if (result.granted) { setAvailable(result.available); setAllocation(result.allocation); } setMessage(`${result.message}${result.order ? ` Safe discharge order: ${result.order.map(i => `Patient ${i + 1}`).join(' → ')}.` : ''}`); };
  return <section className="dm-block"><h4>Multi-resource admission safety (Banker’s algorithm)</h4>
    <p className="dm-muted">A patient group needs several resources at once. Admitting one is allowed only if some order still lets everyone finish; otherwise a ward bed could be held while waiting forever for a ventilator.</p>
    <p className="text-sm">Free [{available.join(', ')}] · state <b>{safe.safe ? 'SAFE' : 'UNSAFE'}</b>{safe.safe ? ` · order ${safe.order.map(i => `Patient ${i + 1}`).join(' → ')}` : ''}</p>
    <div className="dm-table-wrap"><table className="dm-table dm-dense"><thead><tr><th>Patient</th><th>Holding</th><th>Maximum need</th><th>Still needs</th></tr></thead><tbody>{allocation.map((row, index) => <tr key={index}><td>Patient {index + 1}</td><td>{row.join(', ')}</td><td>{maximum[index].join(', ')}</td><td>{safe.need[index].join(', ')}</td></tr>)}</tbody></table></div>
    <div className="dm-row"><label className="dm-inline">Patient<select value={patient} onChange={e => setPatient(Number(e.target.value))}>{allocation.map((_, index) => <option key={index} value={index}>Patient {index + 1}</option>)}</select></label>{labels.map((label, index) => <label key={label} className="dm-inline">{label}<input type="number" min="0" value={request[index]} onChange={e => setRequest(items => items.map((value, i) => i === index ? Number(e.target.value) : value))}/></label>)}<button className="dm-primary" onClick={evaluate}>Request resources</button><button className="dm-btn" onClick={() => { setAllocation(start); setAvailable(free); setMessage('Reset.'); }}>Reset</button></div>
    {message && <p className="dm-callout" role="status">{message}</p>}</section>;
}

export function BedResult({ result }) {
  const { icu, ward, surge, inputs, trace } = result;
  return <div className="dm-bed-result">
    <div className="dm-pools">
      <PoolCard title="ICU pool · critical (P1)" beds={inputs.icuBeds} pool={icu} extra={<p className="dm-muted">If boarding were unlimited, critical patients would wait a mean <b>{minutes(icu.criticalWaitMinutes)}</b> for an ICU bed (Erlang-C). With only {inputs.icuBoard} boarding places the exact mean boarding wait is <b>{hours(icu.meanWaitHours)}</b> and the overflow is diverted.</p>}/>
      <PoolCard title="Ward pool · urgent (P2) + minor (P3)" beds={inputs.wardBeds} pool={ward} extra={<p className="dm-muted">With priority, urgent patients wait <b>{minutes(ward.priorityWaitMinutes.urgent)}</b> and minor patients <b>{minutes(ward.priorityWaitMinutes.minor)}</b> (non-preemptive M/M/c priority).</p>}/>
    </div>
    <section className="dm-block"><div className="dm-block-head"><h4>Surge forecast · arrivals × {surge.multiplier} for {surge.hours} h</h4><span className={`dm-pill ${surge.risk.band.toLowerCase()}`}>{surge.risk.band} {surge.risk.score}</span></div>
      <div className="dm-kpis"><div><span>Ward diversions</span><b>{pct(surge.ward.blocking)}</b></div><div><span>ICU diversions</span><b>{pct(surge.icu.blocking)}</b></div><div><span>Ward busy</span><b>{pct(surge.ward.utilisation)}</b></div><div><span>ICU busy</span><b>{pct(surge.icu.utilisation)}</b></div></div>
      <div className="dm-sparks"><Trajectory fluid={surge.fluidWard} beds={inputs.wardBeds} label="Ward"/><Trajectory fluid={surge.fluidIcu} beds={inputs.icuBeds} label="ICU"/></div>
      <p className="dm-muted">Fluid model: N(t) = N∞ + (N₀ − N∞)e^(−μt); the dashed line is bed capacity. Steady-state diversion probabilities above use the exact M/M/c/K distribution.</p></section>
    <div className="dm-risk-grid"><RiskBreakdown risk={icu.risk} title="ICU risk" compact/><RiskBreakdown risk={ward.risk} title="Ward risk" compact/><RiskBreakdown risk={surge.risk} title="Surge risk" compact/></div>
    <AdmissionBanker/>
    <section className="dm-block"><h4>Semaphore trace · ICU, first {trace.length} events at surge rate</h4><p className="dm-muted">wait = admit to a free bed · signal = discharge · QUEUE = boarding · DIVERT = system full.</p><div className="dm-table-wrap short"><table className="dm-table dm-dense"><thead><tr><th>t (h)</th><th>Event</th><th>Detail</th><th>Free beds</th><th>Boarding</th></tr></thead><tbody>{trace.map((row, index) => <tr key={index}><td>{row.t}</td><td><span className={`dm-key ${row.type === 'DIVERT' ? 'fk' : row.type === 'QUEUE' ? 'unique' : 'pk'}`}>{row.type}</span></td><td>{row.detail}</td><td>{row.free}</td><td>{row.queue}</td></tr>)}</tbody></table></div></section>
    <details className="dm-block"><summary>Formulas and assumptions</summary><ul className="dm-formulas"><li><b>Offered load</b> a = λ/μ, where 1/μ is the mean stay.</li><li><b>Erlang-B</b> B(c,a) = aB(c−1,a) / (c + aB(c−1,a)), B(0,a) = 1.</li><li><b>M/M/c/K</b> P_n ∝ aⁿ/n! for n ≤ c, then (a/c)^(n−c)·a^c/c!; diversion = P_K; λ_eff = λ(1−P_K); L_q = Σ (n−c)P_n; W_q = L_q/λ_eff (Little).</li><li><b>Erlang-C</b> C(c,a) = B / (1 − ρ(1−B)), ρ = a/c &lt; 1.</li><li><b>Priority wait</b> W_k = C(c,a) / [cμ(1−σ_(k−1))(1−σ_k)], σ_k = Σ_(i≤k) λ_i / cμ.</li><li><b>Check</b> an independent seeded discrete-event simulation reproduces the exact diversion probability within its confidence interval.</li></ul>{icu.risk.assumptions.map(text => <p key={text} className="dm-muted">• {text}</p>)}</details>
  </div>;
}
