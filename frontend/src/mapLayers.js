import L from 'leaflet';

export const BAND_COLOR = { clear: '#10b981', caution: '#f59e0b', danger: '#f43f5e' };
export const HAZARD_COLOR = { block: '#64748b', fire: '#f97316', flood: '#06b6d4', earthquake: '#a16207', landslide: '#92400e', traffic: '#eab308' };
export const ALGORITHM_COLOR = { bfs: '#38bdf8', dfs: '#a78bfa', ucs: '#34d399', greedy: '#fb923c', astar: '#f472b6' };

const minutes = seconds => Math.max(1, Math.round(seconds / 60));
const km = meters => (meters / 1000).toFixed(2);

/** Draws a routed result: road-following segments coloured by hazard exposure, closures, baseline, hazard reach and stops. */
export function drawRoute(group, info, { showExplored = false, showBaseline = true } = {}) {
  if (!info) return;
  (info.hazards || []).forEach(hazard => {
    const color = HAZARD_COLOR[hazard.type] || '#64748b';
    L.circle([hazard.lat, hazard.lon], { radius: hazard.influence_radius_m, color, weight: 1.5, dashArray: '6 6', fillColor: color, fillOpacity: .07, interactive: false }).addTo(group);
    if (hazard.closure_radius_m) L.circle([hazard.lat, hazard.lon], { radius: hazard.closure_radius_m, color, weight: 2, fillColor: color, fillOpacity: .22 })
      .bindTooltip(`${hazard.label}: roads within ${hazard.closure_radius_m} m are closed; risk reaches about ${hazard.influence_radius_m} m`).addTo(group);
  });
  if (showExplored) (info.explored || []).forEach(point => L.circleMarker(point, { radius: 1.6, color: '#38bdf8', weight: 0, fillOpacity: .5, interactive: false }).addTo(group));
  if (showBaseline && info.detour?.baseline_coordinates?.length) L.polyline(info.detour.baseline_coordinates, { color: '#94a3b8', weight: 4, dashArray: '9 9', opacity: .9 })
    .bindTooltip(`Route if nothing were closed: ${km(info.detour.baseline_distance_m)} km, ${minutes(info.detour.baseline_eta_s)} min`).addTo(group);
  (info.closures || []).forEach(shape => {
    L.polyline(shape.coordinates, { color: '#ffffff', weight: 11, opacity: .95, interactive: false }).addTo(group);
    L.polyline(shape.coordinates, { color: '#e11d48', weight: 7, opacity: 1 }).bindTooltip(`CLOSED · ${shape.road} · caused by ${shape.cause}`).addTo(group);
    L.polyline(shape.coordinates, { color: '#ffffff', weight: 2, dashArray: '4 6', interactive: false }).addTo(group);
  });
  const seen = new Set();
  (info.closures || []).forEach(shape => {
    if (seen.has(shape.hazard_index)) return;
    seen.add(shape.hazard_index);
    const [[la, lo], [lb, lob]] = shape.coordinates;
    L.marker([(la + lb) / 2, (lo + lob) / 2], { interactive: false, icon: L.divIcon({ className: 'dm-closure-pin', html: '<span>✕</span>', iconSize: [22, 22], iconAnchor: [11, 11] }) }).addTo(group);
  });
  (info.segments || []).forEach(segment => {
    L.polyline(segment.coordinates, { color: '#0b1220', weight: 10, opacity: .9, lineCap: 'round', lineJoin: 'round', interactive: false }).addTo(group);
    L.polyline(segment.coordinates, { color: BAND_COLOR[segment.band], weight: 6, opacity: 1, lineCap: 'round', lineJoin: 'round' })
      .bindTooltip(segment.band === 'clear' ? 'Clear road' : `${segment.band === 'caution' ? 'Caution' : 'High hazard exposure'} · up to ${(segment.max_exposure * 100).toFixed(0)}% exposure`).addTo(group);
  });
  const labels = info.plan?.labels;
  (info.stops || []).forEach((point, index) => {
    L.marker(point, { zIndexOffset: 800, icon: L.divIcon({ className: 'dm-stop-pin', html: `<span>${index + 1}</span>`, iconSize: [22, 22], iconAnchor: [11, 11] }) })
      .bindTooltip(labels?.[index] ? `${index + 1}. ${labels[index]}` : `Stop ${index + 1}`).addTo(group);
  });
}

/** Draws one algorithm's path from the comparison so operators can see how routes differ on real roads. */
export function drawAlgorithmPath(group, name, entry) {
  if (!entry?.coordinates?.length) return;
  const color = ALGORITHM_COLOR[name] || '#fff';
  L.polyline(entry.coordinates, { color: '#0b1220', weight: 9, opacity: .8, interactive: false }).addTo(group);
  L.polyline(entry.coordinates, { color, weight: 5, opacity: 1 }).bindTooltip(`${name.toUpperCase()} · ${km(entry.distance_m)} km · ${minutes(entry.eta_s)} min · risk ${entry.risk_score}`).addTo(group);
  (entry.explored_sample || []).forEach(point => L.circleMarker(point, { radius: 1.8, color, weight: 0, fillOpacity: .55, interactive: false }).addTo(group));
}
