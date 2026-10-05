# Project Report: AI-Based Smart Disaster Response and Rescue Navigation System

## 1. Abstract

This project implements a web-based rescue navigation prototype that uses classical artificial intelligence to find routes in a changing disaster environment. A coordinator places responders, victims, hazards, and facilities on a map-like grid, selects a search strategy, and receives an animated, measured route. The system emphasizes explainable search rather than opaque prediction. It combines a React interface, Flask REST service, SQLite persistence, and five graph-search algorithms.

## 2. Introduction

Disasters degrade roads, obstruct access, create time pressure, and force teams to choose between short and safe routes. Manual planning can be inconsistent when the operational picture changes rapidly. Classical AI search is useful here because its state representation, actions, cost function, and decisions can be inspected by emergency coordinators.

## 3. Problem Statement

Given a rescue team location, one or more victims, and a grid containing inaccessible or slow terrain, find a feasible route and quantify the trade-offs made by several algorithms. The system must also suggest a practical order for attending multiple victims.

## 4. Objectives

The objectives are to implement search algorithms, provide a visual simulator, compare measurable performance, authenticate users, persist scenarios, and expose a modular REST API. A secondary objective is to make every result understandable through replay and metrics.

## 5. Scope

The project models road navigation at grid-cell resolution. It supports locally entered and simulated events. It is not a certified dispatch system, a live GPS tracker, or a replacement for official emergency procedures.

## 6. Stakeholders

Coordinators configure scenarios; responders inspect recommended routes; administrators view system counts; students use the comparison view to understand AI search. Citizens are represented only as victim markers and are not stored as personal records.

## 7. Requirements Analysis

Functional requirements include registration, sign-in, hazard placement, simulation, search, comparison, planning, reporting, and saved scenario APIs. Non-functional requirements include understandable output, responsive layout, safe error messages, modular source files, and repeatable tests.

## 8. Technology Selection

React and Vite give rapid responsive UI development. Flask suits compact, typed Python algorithm modules. SQLite is portable and sufficient for course-scale persistence. Chart.js presents comparisons and jsPDF produces a portable summary. Leaflet is included as the mapping dependency for extension to OpenStreetMap geographic overlays.

## 9. System Architecture

The browser owns the interactive presentation state. It submits JSON to Flask. Flask validates the request and invokes the search engine. SQLite retains users and scenarios. The architecture diagram in `ARCHITECTURE.md` captures this separation, allowing the algorithm engine to be tested without the UI.

## 10. State-Space Model

A state is a passable cell `(r,c)`. Actions are north, south, east, and west. A transition enters an adjacent valid cell. A block, fire, or flood is encoded as `-1` and cannot be entered. Normal terrain costs one; poor-road terrain may cost two or three. The goal is a victim cell.

## 11. Breadth-First Search

BFS uses a FIFO queue and explores by depth. With equal traversal costs it returns a minimum-step path. Its principal drawback is wide memory growth in open terrain. It provides an intuitive baseline because its exploration appears as expanding rings.

## 12. Depth-First Search

DFS uses a stack and follows a branch deeply before backtracking. It can discover a route quickly in favorable layouts, but it does not minimize cost or distance. A visited set prevents cycles. It is included primarily for teaching the effect of frontier discipline.

## 13. Uniform Cost Search

UCS prioritizes accumulated path cost `g(n)`. It is appropriate when road quality varies, because a longer route can be safer or cheaper than a geometrically short damaged road. With nonnegative edge costs, the first popped goal has optimal cost.

## 14. Greedy Best-First Search

Greedy search prioritizes estimated remaining distance only. The Manhattan distance heuristic points it toward the victim. This makes it quick in simple environments, but it may be drawn toward a blocked corridor and its final route is not guaranteed optimal.

## 15. A* Search

A* combines paid cost and estimated remaining cost, `f(n)=g(n)+h(n)`. The app uses Manhattan distance, an admissible heuristic under four-directional movement. A* is selected as the default because it balances route quality with focused exploration.

## 16. Metrics

The service measures elapsed CPU-wall time, visited-node count, final cost, path length, and a simple estimated memory value based on discovered state bookkeeping. Measurements are most meaningful when algorithms are run on the same scenario and machine.

## 17. Visualization Design

The client animates returned visited cells in yellow and then the parent-reconstructed final route in green. Obstacles are dark. Clear contrast makes frontier behavior visible without requiring the coordinator to interpret raw data structures.

## 18. Disaster Simulation

The simulator randomizes passable cells after reserving a team start and hospital. It accepts disaster type, obstacle count, victim count, and road condition. Poor roads introduce weighted cells, highlighting why UCS and A* differ from BFS.

## 19. Multi-Victim Planning

The planning endpoint repeatedly runs A* to candidates and selects the lowest-cost reachable victim. It returns every leg and its path. This greedy nearest-neighbor planning is computationally light and operationally explainable, while acknowledging that global tour optimization is a future enhancement.

## 20. Authentication and Authorization

Passwords are hashed using Werkzeug. Flask issues HS256 JWTs on registration or login. Protected map-simulation reads/writes and administrative statistics require a bearer token. The demonstration admin account is seeded only for local coursework and must be replaced in deployment.

## 21. Data Design

The `users` table contains identity, email, hash, and role. The `simulations` table stores title, serialized scenario JSON, timestamp, and owner reference. This intentionally small schema keeps scenario evolution flexible while the prototype is being evaluated.

## 22. API Design

`/api/auth/register` and `/login` issue credentials. `/search` executes one algorithm; `/compare` executes all five; `/planning` calculates sequence; `/simulation` creates random grids; `/map/simulations` persists or reads scenarios; `/admin/stats` reports protected counts. Invalid inputs return JSON error messages and 400 status where appropriate.

## 23. User Interface

The dashboard separates mission, simulator, comparison, and administrator views. It uses responsive grids, dark mode, clear action buttons, and compact live status. The interaction is designed for demonstration: select an entity, click a cell, then execute an algorithm.

## 24. Security Considerations

Production deployments require environment-managed secrets, HTTPS, explicit CORS origins, request-rate controls, database backups, stronger password policy, audit logs, and expiry/refresh handling for tokens. Sensitive victim information should never be added without a privacy assessment.

## 25. Reliability and Error Handling

The API checks algorithms and passable endpoints, handles duplicate email registration, and returns human-readable JSON errors. A route can legitimately be absent; this is returned as `found: false` rather than treated as a server fault.

## 26. Testing Strategy

Unit tests check that every algorithm finds a valid route in a constrained grid. Manual acceptance testing covers simulation, placement, search replay, charts, login, PDF export, and responsive display. Build validation ensures the frontend bundles without syntax errors.

## 27. Performance Discussion

Grid search is suitable for the small tactical grid. BFS and DFS can grow substantially with map size; UCS and A* maintain priority queues. A* typically explores fewer cells when the heuristic is informative. Server execution time is deliberately shown rather than hidden.

## 28. Ethical and Safety Considerations

Routing advice is assistive, not authoritative. A model cannot know structural collapse, water depth, or responder health unless the inputs represent them. The interface explicitly retains human control and should be used only alongside verified incident information.

## 29. Limitations

The prototype does not ingest live sensor feeds, road networks, elevation, changing hazard intensity, simultaneous teams, or globally optimal vehicle routing. Its grid is an abstraction and its memory metric is an estimate. These constraints make it appropriate for education and controlled demonstrations.

## 30. Future Work

Future iterations can integrate Leaflet drawing and OpenStreetMap road graphs, WebSocket updates, GIS layers, real-time weather, configurable hazard risk costs, exact multi-vehicle planning, role management, offline maps, accessibility auditing, and a formal incident audit trail.

## 31. Conclusion

SentinelAI demonstrates that classical AI search can be made tangible in a modern full-stack system. The project exposes algorithmic trade-offs, visualizes their behavior, and connects planning logic to a credible rescue workflow. It meets the learning objective of applying search and planning techniques to a high-impact domain.

## References

Russell, S. and Norvig, P., *Artificial Intelligence: A Modern Approach*, 4th ed. Flask and React official documentation. OpenStreetMap and Leaflet documentation. Chart.js documentation.
