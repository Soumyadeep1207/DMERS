# AI-Based Smart Disaster Response and Rescue Navigation System

SentinelAI is a full-stack decision-support system for dispatching rescue teams across a dynamic disaster grid. It demonstrates classical Artificial Intelligence search and planning: BFS, DFS, Uniform Cost, Greedy Best-First, A*, and nearest-feasible multi-victim planning.

## Data management

DMERS now has a normalized incident, location, rescue-team, hospital, mission, user/role, and audit model. The workstation uses its SQLite operational cache while offline; `docker compose up -d postgres` provisions the matching PostgreSQL production schema using [the reproducible migration](backend/migrations/001_initial_postgresql.sql). The Data Management view reads only through the Flask API and shows actual persistence health, relational records, and database statistics.

## AI-DMERS advisory layer

The AI endpoints provide authenticated, officer-reviewed classification,
severity, duplicate, credibility and baseline forecast advisories. They never
dispatch or alter operational records. See [AI layer documentation](docs/ai_layer.md).
Install `backend/requirements-ai-training.txt` only when training the optional
learned models; the normal application uses its advisory fallback offline.

## Offline use

The command centre is designed to run without Internet or LAN access. Its map reference layer, facility markers, scenario generator, AI route planner, local accounts, reports, and route estimates all run on the device. Route estimates are straight-line planning estimates, not live road navigation or traffic data.

For a completely disconnected machine, copy this project **including** `frontend/node_modules` and the Python virtual environment after they have been installed once on a connected machine. Then run:

1. `cd frontend; npm run dev` — the interface works by itself at the local URL shown.
2. Optionally, start the backend with `cd backend; .\.venv\Scripts\python.exe run.py` for the SQLite-backed accounts, simulations, and audit log. This remains local-only.

## Initial setup (Internet needed once for packages)

1. `cd backend; python -m venv .venv; .\.venv\Scripts\activate; pip install -r requirements.txt; flask --app run run --debug`
2. In another terminal: `cd frontend; npm install; npm run dev`
3. Open `http://localhost:5173`. API runs at `http://localhost:5000`.

Sample administrator: `admin@rescue.ai` / `Admin@123`. Set a real `SECRET_KEY` for deployment.

## Docker deployment

Docker Compose deploys one DMERS project with separate `frontend` (Nginx),
`backend` (Flask), and `database` (PostgreSQL) containers on an internal
network. Copy `.env.example` to `.env`, replace both placeholder secrets, then
run `docker compose up --build -d`. Open `http://localhost:8080`; inspect
services with `docker compose ps` and logs with `docker compose logs -f`.

## Features

- JWT authentication, registration, and role-protected administrative statistics
- Interactive 20×20 rescue grid with teams, victims, hazards, blocks, hospitals, and safe zones
- Animated search visualization, metrics, replay, PDF export, dark responsive interface
- Random flood, earthquake, and fire scenarios with weighted road conditions
- Algorithm comparison chart, saved simulations, and multi-victim rescue ordering

## Layout

`frontend/` React/Vite dashboard · `backend/` Flask API and SQLite store · `docs/` course documentation · `screenshots/` verification captures.

See [Installation Guide](docs/INSTALLATION.md), [User Manual](docs/USER_MANUAL.md), [Architecture](docs/ARCHITECTURE.md), [Algorithms](docs/AI_ALGORITHMS.md), and [Project Report](docs/PROJECT_REPORT.md).
