export function allocateContiguous(partitions, requests, strategy = 'FIRST_FIT') {
  const holes = partitions.map((size, index) => ({ id: index, start: partitions.slice(0, index).reduce((a, b) => a + b, 0), size, free: true }));
  const placements = [], failed = []; let nextFitStart = 0;
  for (const request of requests) {
    const candidates = holes.filter(hole => hole.free && hole.size >= request.size);
    const selected = strategy === 'BEST_FIT' ? candidates.sort((a, b) => a.size - b.size || a.start - b.start)[0]
      : strategy === 'WORST_FIT' ? candidates.sort((a, b) => b.size - a.size || a.start - b.start)[0]
        : strategy === 'NEXT_FIT' ? [...candidates].sort((a,b)=>a.start-b.start).find(hole=>hole.start>=nextFitStart) || [...candidates].sort((a,b)=>a.start-b.start)[0]
          : candidates.sort((a, b) => a.start - b.start)[0];
    if (!selected) { failed.push({ ...request, reason: 'No single free hole is large enough.' }); continue; }
    placements.push({ request: request.id, start: selected.start, size: request.size, hole: selected.id });
    nextFitStart=selected.start+request.size;
    selected.free = false;
    if (selected.size > request.size) holes.push({ id: holes.length, start: selected.start + request.size, size: selected.size - request.size, free: true });
  }
  const free = holes.filter(hole => hole.free), totalFree = free.reduce((sum, hole) => sum + hole.size, 0), largestHole = Math.max(0, ...free.map(hole => hole.size));
  return { strategy, placements, failed, holes: free, totalFree, largestHole,
    externalFragmentation: totalFree ? 1 - largestHole / totalFree : 0 };
}

export function compactMemory(holes) {
  const total = holes.reduce((sum, hole) => sum + hole.size, 0);
  return { before: { holeCount: holes.length, totalFree: total, largestHole: Math.max(0, ...holes.map(hole => hole.size)) },
    after: { holeCount: total ? 1 : 0, totalFree: total, largestHole: total } };
}

export function translatePagedAddress(logicalAddress, pageSize, pageTable) {
  if (logicalAddress < 0 || pageSize < 1) throw new RangeError('Address must be non-negative and page size positive.');
  const page = Math.floor(logicalAddress / pageSize), offset = logicalAddress % pageSize, frame = pageTable[page];
  if (frame === undefined || frame === null) return { valid: false, page, offset, trap: 'Page is not mapped.' };
  return { valid: true, page, offset, frame, physicalAddress: frame * pageSize + offset,
    arithmetic: `${frame} × ${pageSize} + ${offset} = ${frame * pageSize + offset}` };
}

export function internalFragmentation(processSize, pageSize) {
  if(processSize<0||pageSize<1)throw new RangeError('Process size must be non-negative and page size positive.');
  const allocated=Math.ceil(processSize/pageSize)*pageSize;
  return { processSize, allocated, pages: allocated/pageSize, internalFragmentation: allocated-processSize };
}

export function segmentAddress(segmentTable, segment, offset) {
  const entry = segmentTable[segment];
  if (!entry || offset < 0 || offset >= entry.limit) return { valid: false, trap: 'Segmentation fault: offset is outside the segment limit.' };
  return { valid: true, segment, offset, base: entry.base, physicalAddress: entry.base + offset };
}

export function effectiveAccessTime(hitRatio, memoryTime, tlbTime = 0) {
  const hit = Number(hitRatio), access = Number(memoryTime), tlb = Number(tlbTime);
  if (hit < 0 || hit > 1 || access < 0 || tlb < 0) throw new RangeError('Hit ratio must be 0..1 and access times non-negative.');
  return hit * (tlb + access) + (1 - hit) * (tlb + 2 * access);
}
