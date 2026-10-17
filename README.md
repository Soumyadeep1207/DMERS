# AI-Based Smart Disaster Response and Rescue Navigation System

SentinelAI is a full-stack decision-support system for dispatching rescue teams across a dynamic disaster grid. It demonstrates classical Artificial Intelligence search and planning: BFS, DFS, Uniform Cost, Greedy Best-First, A*, and nearest-feasible multi-victim planning.

## Data management

DMERS uses PostgreSQL when `DATABASE_URL` is configured and falls back to its SQLite operational store for offline/local use. The application database `dmers` stores accounts, incidents, locations, response teams, hospitals, missions, simulations and audit events. The Review II coursework schema is integrated separately as `dmers_course`, preserving both models. Its PostgreSQL 16 scripts implement eight relations, constraints, seeded records, 15 queries, PL/pgSQL functions and procedures, a cursor, and five triggers. The Data Management view can load live application records and the Review II demonstration side by side. See [Review II database integration](docs/review2/README.md).

## Offline use

The command centre is designed to run without Internet or LAN access. Its map reference layer, facility markers, scenario generator, AI route planner, local accounts, reports, and route estimates all run on the device. Route estimates are straight-line planning estimates, not live road navigation or traffic data.

For a completely disconnected machine, copy this project **including** `frontend/node_modules` and the Python virtual environment after they have been installed once on a connected machine. Then run:

1. `cd frontend; npm run dev` — the interface works by itself at the local URL shown.
2. Optionally, start the backend with `cd backend; .\.venv\Scripts\python.exe run.py` for SQLite-backed accounts, simulations, and audit log. This remains local-only.

## Docker setup (Internet needed for the first image build)

1. Start Docker Desktop. Copy `.env.example` to `.env` and replace `POSTGRES_PASSWORD` and `SECRET_KEY` with private values.
2. From the project root, run `powershell -ExecutionPolicy Bypass -File .\start-project.ps1`. The launcher starts PostgreSQL, creates and initializes `dmers_course` once from the checked-in Review II SQL scripts, builds the backend and frontend, and waits until both databases are healthy.
3. Open the command centre at `http://127.0.0.1:5175`. Check `http://127.0.0.1:5003/health`; it reports the connection state of both `dmers` and `dmers_course`.
4. `docker compose ps` shows each service's health. Use `docker compose logs -f backend` to inspect backend startup. Stop the stack with `docker compose down`; this preserves the PostgreSQL volume.

The Compose ports bind to localhost only. PostgreSQL is exposed on `127.0.0.1:5433` (user `dmers`, databases `dmers` and `dmers_course`), Flask on `127.0.0.1:5003`, and the web frontend on `127.0.0.1:5175`. Flask uses port 5003 to avoid the existing service occupying 5001 and the development profile's port 5002. The PostgreSQL password is the private `POSTGRES_PASSWORD` value in the root `.env`. The browser frontend proxies API requests to Flask over Docker's private network.

The default Compose stack is production-style: Gunicorn runs Flask, while a multi-stage frontend image builds static assets and serves them with Nginx. For hot-reload development containers, run `docker compose --profile dev up --build -d postgres backend-dev frontend-dev`; open `http://127.0.0.1:5176` and check `http://127.0.0.1:5002/health`. The development profile uses bind mounts for the application source and shares the same PostgreSQL service.

## AWS deployment

AWS deployment files live separately in [`aws/`](aws/README.md) and use ECS Fargate, ECR, an Application Load Balancer, private RDS PostgreSQL, Secrets Manager, and CloudWatch. They do not replace or alter the local Compose workflow. Follow the [AWS deployment guide](aws/README.md) for prerequisites, image publishing, infrastructure setup, coursework database initialization, health verification, and cleanup. The sample AWS configuration is HTTP-only and intended for a course demo; configure HTTPS before sending any real credentials or incident data.

## Manual/offline setup

For a completely disconnected machine, copy this project including `frontend/node_modules` and the Python virtual environment after they have been installed once on a connected machine. Then run `cd frontend; npm run dev` — the interface works by itself at the local URL shown. Optionally start the backend with `cd backend; .\.venv\Scripts\python.exe run.py` for SQLite-backed accounts, simulations, and audit log.

Sample application administrator: `admin@rescue.ai` / `Admin@123`. Review II coursework demo accounts use `Dmers@2026`; those accounts are data in `dmers_course` and are not application sign-in accounts. Set a real `SECRET_KEY` for deployment.

## Features

- JWT authentication, registration, and role-protected administrative statistics
- Interactive 20×20 rescue grid with teams, victims, hazards, blocks, hospitals, and safe zones
- Animated search visualization, metrics, replay, PDF export, dark responsive interface
- Random flood, earthquake, and fire scenarios with weighted road conditions
- Algorithm comparison chart, saved simulations, and multi-victim rescue ordering
- Live API/database status with refreshable health checks on the sign-in and command-centre views
- Incident triage workflow, hospital/team data views, audit history, and spreadsheet-safe CSV incident export
- Separate production and hot-reload development Docker profiles with PostgreSQL health-gated startup

## Layout

`frontend/` React/Vite dashboard · `backend/` Flask API and SQLite store · `docker-compose.yml` PostgreSQL, API, and web services · `docs/` course documentation · `screenshots/` verification captures.

See [Installation Guide](docs/INSTALLATION.md), [User Manual](docs/USER_MANUAL.md), [Architecture](docs/ARCHITECTURE.md), [Algorithms](docs/AI_ALGORITHMS.md), and [Project Report](docs/PROJECT_REPORT.md).
