# DMERS OS Laboratory

## Purpose and use case

The Operating Systems workspace turns DMERS emergency-response activity into small, repeatable OS experiments. Students can compare how dispatch policies affect response and waiting time, observe race conditions in shared ambulance counts, inspect deadlock detection and prevention, and explore memory, paging, disk scheduling, IPC, and file allocation with deterministic examples.

It is a learning and decision-support simulation. Its generated paths, workloads, timings, and resource outcomes are not live dispatch instructions and do not control the DMERS route planner.

## Integration and preservation

The lab is loaded lazily from the existing DMERS command centre when the OS area is selected. Citizen reporting, staff/admin workflows, AI route recommendations, database-backed records, health checks, and other existing app paths remain in the existing application. The new lab modules live under `frontend/src/modules/os-labs/`; the prior `frontend/src/osAlgorithms.js` helpers and legacy OS components were retained.

## Architecture

- `OSLaboratory.jsx` provides the OS workspace, controlled task editor, presets, policy selection, result views, playback, comparison, explanations, and exports.
- `kernel/` contains deterministic seeded random generation, discrete events, snapshots, step limits, and livelock/deadlock status helpers. CPU scheduling and process CPU/I/O execution use this kernel.
- `scheduling.js` implements FCFS, non-preemptive SJF, SRTF, priority, priority aging, Round Robin, MLFQ, EDF, and Rate Monotonic scheduling. It reports waiting, response, turnaround, utilization, context-switch, and deadline metrics where applicable.
- `processModel.js` models new, ready, running, waiting, and terminated process states, PCB data, and CPU/I/O bursts.
- `synchronisation.js` demonstrates a seeded lost update and mutex serialization, Peterson's algorithm, counting semaphores, bounded producer/consumer, reader/writer observations, dining philosophers, and priority inversion/inheritance.
- `deadlock.js` provides safe-sequence evaluation, Banker-style request checks, wait-for cycle detection, a multi-instance detector, Coffman-condition prevention examples, and a recovery-victim heuristic.
- `memory.js` covers first/best/worst/next fit, fragmentation and compaction, paging translation, segmentation bounds, and TLB effective access-time calculations.
- `virtualMemory.js` covers FIFO, LRU, Optimal, Clock, and LFU page replacement, including the FIFO Belady example and a thrashing curve.
- `diskScheduling.js` covers FCFS, SSTF, SCAN, C-SCAN, LOOK, and C-LOOK with movement totals and starvation-risk context.
- `ipc.js` demonstrates bounded mailbox/pipe blocking and a signal-interrupted operation; `fileSystem.js` compares contiguous, linked, and indexed allocation.
- `worker/` runs UI calculations in a Web Worker when supported, with a synchronous fallback. The generic worker task path handles the non-CPU demos; CPU and process simulations run through the event kernel.
- `frontend/tests/os-laboratory.test.js` and the existing OS tests use Node's built-in test runner.

## Workload and modeling conventions

- Seeded randomness makes the supplied simulations reproducible.
- Priority 1 is the highest priority; ties use stable arrival/order tie-breaking.
- The scheduler supports a configurable context-switch cost. Idle intervals and incomplete/deadline-missed outcomes are represented in results.
- Round Robin enqueues a task arriving at a quantum boundary before re-queuing the expired task.
- MLFQ uses three queues with 2/4/8-unit quanta and demotes tasks that consume a full quantum.
- Rate Monotonic assigns shorter periods higher priority and expands periodic jobs through a finite default horizon; the Liu–Layland bound is a sufficient schedulability test, not a necessary one.
- The memory and paging examples use integer address/frame models. Their outputs describe the selected trace and configured frame sizes only.

## Verification performed

- `npm test`: 18 tests passed, including deterministic replay, scheduling boundaries and metrics, process CPU/I/O states, Banker refusal without mutation, FIFO's 9-versus-10 Belady result, seeded page-replacement invariants, memory bounds/fragmentation, disk movement, synchronization/IPC, deadlock cycle detection, and worker result serialization.
- `npm run build`: production build succeeded; the OS workspace and worker are separate lazy-loaded chunks.
- `npm run os-demo`, `npm run os-sync-demo`, `npm run os-deadlock-demo`, and `npm run os-memory-demo`: completed with the expected comparative outputs.
- `npm run os-bench`: 5,000 scheduler ticks completed in 35.35 ms and 5,000 process instructions in 4.66 ms on the current host. These are local synthetic measurements, not guaranteed performance targets.

## Scope and limitations

The lab is intentionally an educational simulator, not a full operating-system kernel. CPU scheduling and process execution share the discrete-event kernel; the synchronization, deadlock, memory, virtual-memory, disk, IPC, and file-system examples currently return deterministic module-specific traces/results rather than stepping every operation through that same kernel. The reader/writer result is a finite observation, not a general starvation proof. Disk SSTF's starvation note is a risk explanation, not an adversarial workload proof. TLB output is an effective-access-time calculation, not a generated TLB hit/miss stream. Compaction, recovery, and file-allocation choices are represented through outputs and examples rather than persistent OS state or real rollback. Web Workers keep supported computations off the UI thread, but fallback mode runs them synchronously.
