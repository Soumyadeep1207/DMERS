import React, { useCallback, useEffect, useState } from 'react';
import { get } from '../api.js';
import { Chip, Field, Notice, Section, Table, message, useBusy } from './labUi.jsx';

function Series({ points }) {
  if (!points.length) return null;
  const W = 640, H = 150, pad = 20, max = Math.max(...points.map(p => p.n), 1);
  const x = i => pad + (i / (points.length - 1)) * (W - 2 * pad), y = v => H - pad - (v / max) * (H - 2 * pad);
  return <svg viewBox={`0 0 ${W} ${H}`} className="lab-map" role="img" aria-label="Daily incidents with trailing mean and spikes">
    <polyline fill="none" stroke="currentColor" strokeWidth="1.2" opacity=".6" points={points.map((p, i) => `${x(i).toFixed(1)},${y(p.n).toFixed(1)}`).join(' ')} />
    <polyline fill="none" stroke="var(--dm-accent)" strokeWidth="2" points={points.map((p, i) => `${x(i).toFixed(1)},${y(p.trailing_mean ?? p.n).toFixed(1)}`).join(' ')} />
    {points.map((p, i) => p.spike && <g key={i}><circle cx={x(i)} cy={y(p.n)} r="5" fill="none" stroke="var(--dm-severe)" strokeWidth="2.5" /><text x={x(i) + 7} y={y(p.n) + 4} fontSize="10" fill="currentColor">{p.day}</text></g>)}
  </svg>;
}

/** Idea 8: window functions and regression aggregates do the forecasting inside PostgreSQL. */
export default function AnalyticsLab() {
  const [params, setParams] = useState({ window: 14, threshold: 5 });
  const [data, setData] = useState(null);
  const [zone, setZone] = useState(null);
  const [series, setSeries] = useState([]);
  const [error, setError] = useState('');
  const [busy, guard] = useBusy();

  const run = useCallback(guard(async () => {
    const r = await get(`/api/response/lab/analytics?${new URLSearchParams(params)}`);
    if (r.ok) { setData(r.body); setError(''); const z = r.body.spikes[0]?.zone_id ?? r.body.forecast[0]?.zone_id; setZone(prev => prev ?? z ?? null); }
    else { setData(null); setError(message(r)); }
  }), [params]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { run(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (zone == null) return; (async () => { const r = await get(`/api/response/lab/analytics/series?${new URLSearchParams({ zone_id: zone, window: params.window, threshold: params.threshold })}`); if (r.ok) setSeries(r.body.series); })(); }, [zone, data]); // eslint-disable-line react-hooks/exhaustive-deps

  return <Section eyebrow="Database lab 8 · window functions" title="Incident analytics inside the database"
    why="Trailing mean and standard deviation per zone (avg / stddev_samp over a sliding window) flag surges by z-score; regr_slope and regr_intercept fit a least-squares trend and forecast the next week. All of it is SQL over the synthetic history, with no Python loop.">
    <div className="rs-inline">
      <Field label="Trailing window (days)"><input type="number" min="7" max="60" value={params.window} onChange={e => setParams({ ...params, window: e.target.value })} /></Field>
      <Field label="Spike threshold (z-score)"><input type="number" min="1" max="20" step="0.5" value={params.threshold} onChange={e => setParams({ ...params, threshold: e.target.value })} /></Field>
      <button className="dm-primary" onClick={run} disabled={busy}>Recompute in PostgreSQL</button>
    </div>
    {error && <Notice tone="bad">{error}</Notice>}
    {data && <>
      <h3>Surges found ({data.spikes.length})</h3>
      <Table columns={['Zone', 'Day', 'Incidents', 'Trailing mean', 'Std dev', 'z-score', '']} rows={data.spikes.map(s => [s.zone, s.day, <strong>{s.n}</strong>, s.trailing_mean, s.trailing_sd, <strong>{s.z_score}</strong>,
        <button className="dm-btn" onClick={() => setZone(s.zone_id)}>Chart</button>])} empty="No surge at this threshold." />
      {series.length > 0 && <><p className="rs-muted">Zone {data.forecast.find(f => f.zone_id === zone)?.zone || zone}: grey = incidents per day, blue = trailing mean, red ring = surge.</p><Series points={series} /></>}
      <h3>Next-7-day forecast (linear trend over the last 28 days)</h3>
      <Table columns={['Zone', 'Avg last 7 d', 'Avg 28 d', 'Trend / day', 'R²', 'Tomorrow', 'Next 7 days']} rows={data.forecast.map(f => [f.zone, f.avg_last_7, f.avg_history, f.slope_per_day, f.r_squared, f.forecast_next_day, <strong>{f.forecast_horizon_total}</strong>])} />
      <p className="rs-muted">{data.note} A low R² means the trend explains little: treat these as planning hints, not predictions. <Chip tone="info">synthetic data</Chip></p>
    </>}
  </Section>;
}
