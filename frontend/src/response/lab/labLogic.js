/** Pure helpers for the Database Lab (no React, no network) so they can be unit-tested with node:test. */

export const formatBytes = bytes => {
  if (bytes === null || bytes === undefined) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
};

export const shortHash = hex => (hex ? `${hex.slice(0, 8)}…${hex.slice(-4)}` : '(none: first entry)');

/** Server-sent events: split a text buffer into complete messages and the unfinished rest. Comments (": ...") are skipped. */
export function parseSse(buffer) {
  const events = [];
  const parts = buffer.split('\n\n');
  const rest = parts.pop();
  for (const part of parts) {
    const data = part.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n');
    if (!data) continue;
    try { events.push(JSON.parse(data)); } catch { /* a malformed message is ignored, never fatal */ }
  }
  return { events, rest };
}

/** One readable line for a live event. */
export function describeEvent(event) {
  if (event.table === 'incidents') return `Incident #${event.incident_id} ${event.op === 'INSERT' ? 'reported' : `is now ${event.status}`} (${event.severity})`;
  if (event.table === 'dispatches') return `Unit #${event.unit_id} ${event.op === 'INSERT' ? 'dispatched to' : `is ${event.status} at`} incident #${event.incident_id}`;
  return JSON.stringify(event);
}

/** Bars for the plan tree: width is each node's share of the slowest node (never 0 so every node stays visible). */
export function planBars(nodes) {
  const peak = Math.max(...nodes.map(n => (n.ms || 0) * (n.loops || 1)), 0.001);
  return nodes.map(n => ({ ...n, share: Math.max(2, Math.round(100 * ((n.ms || 0) * (n.loops || 1)) / peak)) }));
}

/** How many times faster `fast` is than `slow` (execution time), as text. */
export const speedup = (slow, fast) => (slow > 0 && fast > 0 ? `${(slow / fast).toFixed(slow / fast >= 10 ? 0 : 1)}x` : '—');

/** Fit lat/lon polylines into an SVG box, north up. Returns point strings and a projector for extra markers. */
export function fitPath(points, width, height, pad = 14) {
  if (!points?.length) return { line: '', project: () => [0, 0] };
  const lats = points.map(p => p[0]), lons = points.map(p => p[1]);
  const [minLat, maxLat, minLon, maxLon] = [Math.min(...lats), Math.max(...lats), Math.min(...lons), Math.max(...lons)];
  const kx = Math.cos(((minLat + maxLat) / 2) * Math.PI / 180);                     // keep the aspect ratio of the real ground
  const spanX = Math.max((maxLon - minLon) * kx, 1e-6), spanY = Math.max(maxLat - minLat, 1e-6);
  const scale = Math.min((width - 2 * pad) / spanX, (height - 2 * pad) / spanY);
  const project = ([lat, lon]) => [pad + (lon - minLon) * kx * scale, height - pad - (lat - minLat) * scale];
  return { line: points.map(p => project(p).map(v => v.toFixed(1)).join(',')).join(' '), project };
}

/** Plain-language cell for the isolation matrix. */
export const matrixTone = cell => (cell === 'anomaly' ? 'bad' : cell.startsWith('prevented') ? 'info' : 'ok');

/** datetime-local value (no zone) to the ISO string the API expects, treated as Indian Standard Time. */
export const localToApi = value => (!value ? '' : `${value.length === 16 ? `${value}:00` : value}+05:30`);

/** Days between two ISO dates (inclusive), used to cap free-window queries on the client as well. */
export const daysBetween = (from, to) => Math.round((new Date(to) - new Date(from)) / 86400000);
