# Running the Review III demonstration

Everything below was run on Windows 11 with Docker Desktop (PostgreSQL 16, Python 3.12 in the backend image).
Commands are PowerShell; run them from the repository root.

## 1. Start the stack

```powershell
Copy-Item .env.example .env          # first time only; then put private values in POSTGRES_PASSWORD and SECRET_KEY
powershell -ExecutionPolicy Bypass -File .\start-project.ps1
```

The launcher starts PostgreSQL, builds the backend and frontend, and waits for health. On start the backend:

1. applies the pending migrations in order (`001` baseline, `002` incident-response model, `003` unit-lead rule) and records them in `schema_migrations`;
2. with the Compose defaults `DMERS_DEMO_MODE=1`, `DMERS_ALLOW_DEMO_SEED=1` and `DMERS_AUTO_SEED_RESPONSE=1`, loads the Review II
   history (14 incidents, 61 timeline entries, 16 dispatches, 15 allocations) into schema `response` if it is empty.

Check it:

```powershell
curl.exe -s http://127.0.0.1:5003/health
```

`response_model.migration_level` must be `002` and `response_model.ok` must be `true`.

## 2. Use the application

* Open `http://127.0.0.1:5175`. If you still see an older interface, press Ctrl+F5 once.
* Sign in as the seeded administrator `admin@rescue.ai` (password in the README).
* **Response Ops** tab: report, verify, dispatch, progress, allocate, close, restock and delete, as the account type allows.
* Sign in as a demonstration person to act in their role (password `Dmers@2026`, shared by all of them):

| Person | Account type | E-mail |
|---|---|---|
| Priya Natarajan | COORDINATOR | `priya.natarajan@dmers.example.org` |
| Divya Ramesh | UNIT_LEAD (leads Katpadi Fire Unit) | `divya.ramesh@dmers.example.org` |
| Gopal Iyer | CITIZEN | `gopal.iyer@mail.example.com` |
| Meena Krishnan | ADMINISTRATOR | `meena.krishnan@dmers.example.org` |

* **Database activity** (button at the bottom right) opens the drawer that explains every operation as the five guideline questions.
* **Reports** tab: nine reports with CSV and black-and-white PDF export.
* **Administration** tab (administrator only): create and edit zones, response units and relief items.

## 3. Guided demo

Sign in as the administrator and open `http://127.0.0.1:5175/demo`. Use **Reset demonstration data**, then **Next step**
(or **Run all remaining**). It runs 32 steps covering T1 to T11, including the refusals.

## 4. Headless demo and evidence log

```powershell
python scripts\demo_transactions.py
```

It prints each step's `db_trace` and rewrites `docs/review3/demo_run_log.txt`. It exits with status 1 if any step does not behave
as expected. Use `--no-reset` to keep the current data.

## 5. Tests

PostgreSQL must be reachable (the Compose database is used; each test gets its own disposable copy).

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests -q          # 95 tests
cd ..\frontend
npm test                                               # 42 tests
npm run build
```

Set `DMERS_REQUIRE_PG=1` to make a missing PostgreSQL fail the tests instead of skipping the database ones.

## 6. Without Docker

```powershell
cd backend
$env:DATABASE_URL = "postgresql://dmers:<password>@127.0.0.1:5433/dmers"
$env:DMERS_ALLOW_DEMO_SEED = "1"; $env:DMERS_DEMO_MODE = "1"
.\.venv\Scripts\python.exe -m db.seed_demo --reset      # applies migrations, then loads the demonstration data
.\.venv\Scripts\python.exe run.py
```

`flask --app run seed-demo` does the same through Flask (`DMERS_SEED_RESET=1` to reset). Without `DATABASE_URL` the application uses the
SQLite fallback and the response endpoints answer HTTP 501.

## 7. Course database scripts

The Review II scripts still run on their own against `dmers_course`:

```powershell
docker compose exec -T postgres psql -U dmers -d dmers_course -v ON_ERROR_STOP=1 -f /review2/run_all.sql
```

A copy of them lives in `backend/db/review2/`; a test asserts it is identical to `docs/review2/sql/`.
