export function scheduleDisk(requests, head, algorithm = 'FCFS', direction = 'right', diskSize = 200) {
  const queue = requests.map(Number);
  if (!Number.isInteger(head) || head < 0 || head >= diskSize || queue.some(value => !Number.isInteger(value) || value < 0 || value >= diskSize)) throw new RangeError('Head and requests must be valid tracks on the configured disk.');
  const left = queue.filter(value => value < head).sort((a, b) => b - a), right = queue.filter(value => value >= head).sort((a, b) => a - b);
  let path;
  if (algorithm === 'FCFS') path = queue;
  else if (algorithm === 'SSTF') { const remaining = [...queue]; path = []; let current = head; while (remaining.length) { const nearest = remaining.reduce((best, value) => Math.abs(value - current) < Math.abs(best - current) ? value : best); path.push(nearest); remaining.splice(remaining.indexOf(nearest), 1); current = nearest; } }
  else if (algorithm === 'SCAN') path = direction === 'right' ? [...right, ...(left.length ? [diskSize - 1, ...left] : [])] : [...left, ...(right.length ? [0, ...right] : [])];
  else if (algorithm === 'C-SCAN') path = direction === 'right' ? [...right, ...(left.length ? [diskSize - 1, 0, ...[...left].reverse()] : [])] : [...left, ...(right.length ? [0, diskSize - 1, ...[...right].reverse()] : [])];
  else if (algorithm === 'LOOK') path = direction === 'right' ? [...right, ...left] : [...left, ...right];
  else if (algorithm === 'C-LOOK') path = direction === 'right' ? [...right, ...[...left].reverse()] : [...left, ...[...right].reverse()];
  else throw new RangeError(`Unknown disk algorithm: ${algorithm}`);
  const points = [head, ...path]; const totalMovement = points.slice(1).reduce((sum, track, index) => sum + Math.abs(track - points[index]), 0);
  return { algorithm, direction, path: points, requests: queue, totalMovement, averageSeek: queue.length ? totalMovement / queue.length : 0,
    starvationRisk: algorithm === 'SSTF' ? 'Possible if new nearby requests keep arriving; a finite input queue cannot prove starvation.' : null };
}
