# Architecture and Flowcharts

```mermaid
flowchart LR
  U[Rescue coordinator] --> R[React + Vite dashboard]
  R -->|JSON / REST| F[Flask API]
  F --> A[Search and planning engine]
  F --> D[(SQLite)]
  A --> B[BFS / DFS / UCS / Greedy / A*]
  R --> C[Chart.js metrics and grid animation]
```

```mermaid
flowchart TD
  S[Create or simulate scenario] --> V[Validate team, victim and grid]
  V --> Q[Select AI algorithm]
  Q --> E[Expand frontier]
  E --> G{Goal reached?}
  G -- No --> E
  G -- Yes --> P[Reconstruct parents into path]
  P --> M[Return metrics and animate route]
```

The UI holds the map/grid state. Flask is the authoritative executor for planning and search. SQLite persists user and scenario records. Hazards and blocks are impassable (`-1`); poor roads carry a positive traversal cost.
