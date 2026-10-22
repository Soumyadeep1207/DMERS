# Real-road routing, risk model, hospital beds and schema exports

This note explains how DMERS ties its AI and OS modules to Vellore as it really is, and how every
number it shows can be traced back to a formula.

## 1. Real roads, not a grid

* **Data**: drivable roads of Vellore (bounding box 12.875–12.960 N, 79.095–79.175 E) from OpenStreetMap,
  fetched once from the Overpass API and stored in `backend/app/data/vellore_roads.json`
  (16,352 junction nodes, 35,388 directed edges, one-way rules, road classes, bridges, surface, names).
  Facilities (58 hospitals, 5 police stations, 4 shelters, 1 fire station) are in
  `backend/app/data/vellore_facilities.json`. © OpenStreetMap contributors, ODbL 1.0.
* **Offline**: after that one download nothing leaves the machine; the algorithms run in the Flask service.
* **Rebuild**: `backend/tools/build_road_graph.py` and `backend/tools/build_facilities.py` contain the
  Overpass queries and turn a raw export into the bundled files (`python -I tools/build_road_graph.py raw.json app/data/vellore_roads.json`).
* **Limits**: OSM has no live traffic and no bed counts. Travel time = length / speed from the road class
  (or `maxspeed` tag), scaled by weather. Bed counts are entered in DMERS, never invented.

## 2. Hazards, closures and blocks

| Marker | Closes roads within | Risk reaches (σ) | Peak severity | Slowdown at centre |
|---|---|---|---|---|
| Road block | 35 m | 45 m | 1.00 | – |
| Fire | 45 m | 160 m | 0.90 | +50 % |
| Flood | 70 m | 260 m | 0.80 | +80 % |
| Earthquake damage | 45 m | 190 m | 0.85 | +60 % |
| Landslide | 55 m | 200 m | 0.80 | +60 % |
| Traffic disruption | – | 220 m | 0.15 | +160 % |

Every road segment closer than the closure radius is **impassable for all five algorithms**. Elsewhere the
exposure of a segment is `1 − Π(1 − severity · exp(−(d/σ)²))` over all hazards, where *d* is the distance from
the marker to the segment. On the map closed segments are red/white dashed with an ✕ pin, the hazard's reach
is a dashed circle, and the grey dashed line is the same trip with no hazards so the detour is visible.

## 3. Search algorithms on the road graph

BFS, DFS, uniform-cost, greedy best-first and A\* all run on the same graph and closures. Weighted searches
minimise `time × (1 + λ × exposure)` with λ = 0 (fastest), 4 (balanced) or 12 (safest). A\* uses
`straight-line distance / fastest speed in the graph` as its heuristic, which never overestimates, so A\*
returns the same optimum as uniform-cost while expanding fewer nodes. *Compare all five* reports distance,
time, risk, nodes expanded and the optimality gap on the operator's own scenario.

Multi-victim plans use exact search over every visiting order (up to 7 victims) with the hospital for each victim
chosen by **routed** cost, then fall back to nearest-feasible ordering for 8–10 victims.

## 4. Risk is explained in every calculation

Each score is `100 × Σ weight × normalised factor`, bands < 20 LOW, < 40 MODERATE, < 65 HIGH, otherwise SEVERE.
The UI lists every factor with its raw value, weight and points, plus the formula and assumptions.

* **Route risk**: chance the route is compromised (35 %), hazard-weighted distance (20 %), slowdown vs clear
  free flow (15 %), unpaved share (10 %), detour caused by hazards (10 %), trip duration (10 %).
* **Situation risk**: hazard load, victims waiting, weather, closed segments.
* **Incident advisory** (`/api/ai/assess`): severity, awaiting action, location confidence, receiving-capacity strain.
* **Grid planner** (`/api/ai/route-plan`): hazard cells, poor-road cells, uncovered targets, length.
* **Hospital beds**: diversion probability, utilisation pressure, priority wait, bed shortfall.

These are decision-support indicators, not calibrated probabilities of harm.

## 5. Hospital bed management (OS Laboratory → Hospital beds)

A bed pool is a counting semaphore: admit = wait(), discharge = signal(), boarding patients are the blocked queue,
diverted ambulances are failed `try_wait()` calls. The module uses exact queueing theory:

* offered load `a = λ/μ`; Erlang-B `B(c,a) = aB(c−1,a)/(c + aB(c−1,a))`; Erlang-C `C = B/(1 − ρ(1−B))`;
* **M/M/c/K** steady state `P_n ∝ aⁿ/n!` (n ≤ c) then `(a/c)^(n−c)·a^c/c!`; diversion `P_K`, `λ_eff = λ(1−P_K)`,
  `W_q = L_q/λ_eff` (Little);
* non-preemptive priority waits `W_k = C(c,a) / [cμ(1−σ_{k−1})(1−σ_k)]`;
* bed sizing (fewest beds for ≤ 1 % diversion), fluid surge model `N(t) = N∞ + (N₀−N∞)e^(−μt)`;
* a seeded discrete-event simulation that must agree with the exact diversion probability (shown with a 95 % interval);
* a Banker's-algorithm panel so an admission is only accepted if beds, ventilators and nurses can all still be completed.

Assumptions: Poisson arrivals, exponential stays, identical beds, stationary rates. Defaults are illustrative.
Tests (`frontend/tests/hospitalBeds.test.js`) check published Erlang-B values, the M/M/1/K closed form,
Little's law and the simulation cross-check.

## 6. Schema documentation CSVs (Data tab, admin/official only)

| File | Content |
|---|---|
| `dmers-schema-dictionary.csv` | one row per column: type, nullability, default, keys, referenced column, delete rule, CHECK rule, index, business meaning, sensitivity, row/null/distinct counts, min/max, masked sample |
| `dmers-relationships.csv` | every foreign key with cardinality, optional/mandatory participation, live orphan count and join SQL |
| `dmers-constraints.csv` | primary keys, UNIQUE, FOREIGN KEY, CHECK, NOT NULL and indexes |
| `dmers-database-export.zip` | the three above, every table's rows, a README manifest and SHA-256 checksums |

Built from the live catalogue on both SQLite and PostgreSQL. Password hashes are never exported, e-mail addresses are
masked, spreadsheet formulas in cell text are neutralised, and every export is written to the audit trail.

## 7. Also changed

* Session tokens now expire (8 h, `DMERS_TOKEN_HOURS`); expired tokens return a clear 401.
* `index.html` is served with `Cache-Control: no-cache` so a redeploy is visible immediately. If you still see the
  old interface after upgrading, hard-refresh once (Ctrl+F5) to drop the copy your browser cached earlier.
* The algorithm selector previously showed BFS while A\* was active; selection now matches behaviour.
* Selecting a hazard tool no longer drops a phantom marker at the city centre.
