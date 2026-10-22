import React from 'react';

const BAND_CLASS = { LOW: 'low', MODERATE: 'moderate', HIGH: 'high', SEVERE: 'severe' };

/** Semicircle gauge: 0-100 on a 180 degree arc, coloured by risk band. */
export function RiskGauge({ score, band, size = 120 }) {
  const radius = 46, circumference = Math.PI * radius;
  const filled = Math.max(0, Math.min(100, score)) / 100 * circumference;
  return <div className={`dm-gauge dm-band-${BAND_CLASS[band] || 'low'}`} style={{ width: size }} role="img" aria-label={`Risk ${score} of 100, ${band}`}>
    <svg viewBox="0 0 120 70"><path d="M14 60 A46 46 0 0 1 106 60" className="dm-gauge-track" pathLength={circumference}/><path d="M14 60 A46 46 0 0 1 106 60" className="dm-gauge-fill" strokeDasharray={`${filled} ${circumference}`}/></svg>
    <b>{Math.round(score)}</b><span>{band}</span>
  </div>;
}

/**
 * Renders one backend/worker risk object: score, band, guidance, and every factor with its weight,
 * normalised value and points, so the operator sees which input moved the number.
 */
export default function RiskBreakdown({ risk, title = 'Risk breakdown', compact = false }) {
  if (!risk) return null;
  const band = BAND_CLASS[risk.band] || 'low';
  return <section className={`dm-risk dm-band-${band}`} aria-label={title}>
    <header><RiskGauge score={risk.score} band={risk.band} size={compact ? 96 : 120}/><div><p className="dm-eyebrow">{title}</p><h4>{risk.band} risk · {risk.score}/100</h4><p className="dm-muted">{risk.guidance || 'Decision-support indicator; confirm with field information.'}</p>{risk.top_factor && <p className="dm-chip">Largest contributor: {risk.top_factor}</p>}</div></header>
    <ul className="dm-factors">{risk.factors.map(item => <li key={item.name}>
      <div className="dm-factor-head"><span>{item.name}</span><b>{item.points.toFixed(1)} pts</b></div>
      <div className="dm-bar" title={`${(item.normalised * 100).toFixed(0)}% of this factor's range`}><i style={{ width: `${Math.max(2, item.normalised * 100)}%` }}/></div>
      <small>{item.value !== '' && item.value !== undefined ? <><b>{String(item.value)}{item.unit ? ` ${item.unit}` : ''}</b> · </> : null}weight {Math.round(item.weight * 100)}% · {item.note}</small>
    </li>)}</ul>
    {!compact && <details><summary>How this score is calculated</summary><p className="dm-formula">{risk.formula}</p><ul>{risk.assumptions.map(text => <li key={text}>{text}</li>)}</ul></details>}
  </section>;
}
