export function allocateFiles(files, blockCount, scheme = 'CONTIGUOUS') {
  let nextBlock = 0; const allocated = [];
  for (const file of files) {
    const blocks = Array.from({ length: file.blocks }, (_, index) => nextBlock + index);
    if (nextBlock + file.blocks > blockCount) { allocated.push({ name: file.name, error: 'Insufficient device blocks.' }); continue; }
    nextBlock += file.blocks;
    allocated.push({ name: file.name, blocks: scheme === 'LINKED' ? blocks.map((block, index) => ({ block, next: blocks[index + 1] ?? null }))
      : scheme === 'INDEXED' ? { indexBlock: blocks[0], dataBlocks: blocks.slice(1) } : blocks });
  }
  return { scheme, allocated, usedBlocks: nextBlock, freeBlocks: blockCount - nextBlock,
    randomAccessCost: scheme === 'LINKED' ? 'O(n) block traversal' : scheme === 'INDEXED' ? 'O(1) through index block' : 'O(1) by direct block offset',
    fragmentation: scheme === 'CONTIGUOUS' ? 'External fragmentation can prevent a large contiguous allocation despite free blocks.' : 'No external fragmentation in this simple block-list model.' };
}
