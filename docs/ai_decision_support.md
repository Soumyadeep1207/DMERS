# AI-DMERS route and triage decision support

Pure, dependency-free JavaScript under `frontend/src/modules/ai/`. Every
function takes explicit inputs (grid, clock, seed) and returns a value; none
touches the DOM, `fetch`, browser storage, or a database. No function
assigns a team, dispatches a unit, or changes an incident/mission status —
every result is a recommendation for a human to act on.

## Modules

| File | Responsibility |
|---|---|
| `advisory.js` | Shared envelope (`makeAdvisory`) all five advisory kinds use. Validates non-empty evidence/limitations, score in `[0,1]` or `null`, and that evidence contributions sum to the score within `1e-9` when `score` is not null. |
| `policies.js` | Frozen `fastest`/`balanced`/`safer` weight table, `cellCost`, and `choosePolicy` (rules R1-R4, evaluated in order). |
| `search.js` | BFS, DFS, UCS, Greedy and A* behind one shared best-first engine and one result contract (`path`, `cost`, `distanceUnits`, `riskScore`, `nodesExplored`, `optimal`, `status`). |
| `multitarget.js` | Greedy nearest-reachable-target ordering with up to two policy alternatives, each carrying its own legs/cost/risk/evidence. |
| `scenario.js` | Seeded, pure PRNG (`seededRng`) and `applyScenario`, which only ever worsens cells and never reopens a blocked one. |
| `playback.js` | Replays an already-computed route one cell at a time; never re-runs search. |
| `triage.js` | Incident scoring, team ranking, and hospital eligibility/ordering. |
| `gridAdapter.js` | Converts the Command Centre's numeric training grid into the weighted-cell format the above modules use. |

## Units and claims

- Route cost is in **grid-cost units**, never presented as travel time.
- `optimal: true` is returned only by UCS and A*, and only means optimal for
  the grid-cost objective defined by the active policy's weights - not a
  claim about real-world travel time or an unweighted hop count.
- Hospital matching is an **eligibility filter** (free beds + accepting
  transfers) ordered by route cost; it is not a weighted prediction score,
  so its advisories carry `score: null`.
- Multi-target ordering is a **greedy heuristic**, not a globally optimal
  tour; every advisory and the UI both state this.

## Demo scripts

`npm run ai-policies|ai-search|ai-auto|ai-triage|ai-scenario` (from
`frontend/`) each exercise the real functions above against a constructed
fixture grid (`scripts/fixtures.js`) — see that file's comment for how the
fixture forces three distinct route-policy outcomes.

## Tests

`npm test` (or `npm run test:coverage`) runs the Vitest suite under
`src/modules/ai/*.test.js`. Statement coverage for `src/modules/ai` is
enforced at 90%+ by `vitest.config.js`.

## UI integration

`frontend/src/RealMapApp.jsx`'s "AI Simulator" tab wires these modules into
the Command Centre: a route-policy selector next to the algorithm selector,
a five-algorithm comparison table, seeded disaster-event application with
automatic replanning, and route playback. The "Explainable advisory review"
section demonstrates `choosePolicy`, `incidentAdvisory`, `rankTeams`, and
`matchHospitals` with their full evidence/limitations.

## Known limitation

The numeric training grid (`gridAdapter.js`'s input) predates this layer and
carries no hazard/exposure data of its own - both start at 0 until a
scenario is applied. It is not connected to the Leaflet map's real-world
GPS markers; the two coexist in the same screen but compute independently.
