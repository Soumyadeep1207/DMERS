const tie = (a, b) => a - b;

/** FIFO, LRU, Optimal, Clock and LFU page replacement with per-reference frame traces. */
export function replacePages(references, frameCount, algorithm = 'FIFO') {
  const refs = Int32Array.from(references, Number), capacity = Math.floor(Number(frameCount));
  if (!Number.isInteger(capacity) || capacity < 1) throw new RangeError('frameCount must be a positive integer.');
  const frames = new Int32Array(capacity).fill(-1), lastUsed = new Map(), frequency = new Map(), trace = [], evictions = [];
  const referenceBits = new Uint8Array(capacity); let hand = 0, fifoPointer = 0, faults = 0, hits = 0;
  for (let i = 0; i < refs.length; i += 1) {
    const page = refs[i]; let slot = frames.indexOf(page); const hit = slot >= 0;
    if (hit) { hits += 1; lastUsed.set(page, i); frequency.set(page, (frequency.get(page) || 0) + 1); referenceBits[slot] = 1; }
    else {
      faults += 1; slot = frames.indexOf(-1);
      if (slot < 0) {
        let victim;
        if (algorithm === 'FIFO') { victim = fifoPointer; fifoPointer = (fifoPointer + 1) % capacity; }
        else if (algorithm === 'LRU') victim = Array.from(frames.keys()).reduce((best, k) => lastUsed.get(frames[k]) < lastUsed.get(frames[best]) ? k : best, 0);
        else if (algorithm === 'OPTIMAL') victim = Array.from(frames.keys()).reduce((best, k) => {
          const nextK = refs.indexOf(frames[k], i + 1), nextBest = refs.indexOf(frames[best], i + 1);
          return (nextK < 0 ? Infinity : nextK) > (nextBest < 0 ? Infinity : nextBest) ? k : best;
        }, 0);
        else if (algorithm === 'LFU') victim = Array.from(frames.keys()).reduce((best, k) => (frequency.get(frames[k]) ?? 0) < (frequency.get(frames[best]) ?? 0) || ((frequency.get(frames[k]) ?? 0) === (frequency.get(frames[best]) ?? 0) && lastUsed.get(frames[k]) < lastUsed.get(frames[best])) ? k : best, 0);
        else if (algorithm === 'CLOCK') {
          while (referenceBits[hand]) { referenceBits[hand] = 0; hand = (hand + 1) % capacity; }
          victim = hand; hand = (hand + 1) % capacity;
        } else throw new RangeError(`Unknown page replacement algorithm: ${algorithm}`);
        evictions.push({ referenceIndex: i, page: frames[victim], replacedBy: page }); slot = victim;
      }
      frames[slot] = page; lastUsed.set(page, i); frequency.set(page, (frequency.get(page) || 0) + 1); referenceBits[slot] = 1;
    }
    trace.push({ referenceIndex: i, page, hit, frames: Array.from(frames), faultCount: faults });
  }
  return { algorithm, trace, faults, hits, hitRatio: refs.length ? hits / refs.length : 0, evictions };
}

export function beladyDemonstration() {
  const references = [1,2,3,4,1,2,5,1,2,3,4,5];
  return { references, threeFrames: replacePages(references, 3, 'FIFO'), fourFrames: replacePages(references, 4, 'FIFO') };
}

export function thrashingCurve(references, maximumFrames = 10, algorithm = 'LRU') {
  return Array.from({ length: maximumFrames }, (_, index) => ({ frames: index + 1, faults: replacePages(references, index + 1, algorithm).faults }));
}
