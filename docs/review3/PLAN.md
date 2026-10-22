# Review III plan: integrating the Review II database into the running DMERS application

Written after reading the Docker Compose file, `backend/app/*`, `backend/migrations/001_initial_postgresql.sql`,
the React client, and every file in `docs/review2/sql/` (copied to `backend/db/review2/`).

## 1. What the repository actually contains

| Topic | Deployed application database (`dmers`, migration 001) | Review II model (`dmers_course`) |
|---|---|---|
| `users` id | `BIGSERIAL` | `INTEGER GENERATED ALWAYS AS IDENTITY` |
| `users` columns | `name`, `email` (UNIQUE), `password`, `role`, `created_at` | `full_name`, `email` (UNIQUE + format CHECK), `password_hash`, `account_type`, `created_at` |
| user type labels | `role` ∈ admin, official, responder, volunteer, citizen (registration sends citizen / volunteer / responder; partner accounts are provisioned by an admin) | `account_type` ∈ CITIZEN, COORDINATOR, UNIT_LEAD, ADMINISTRATOR |
| password hash | Werkzeug `generate_password_hash` (scrypt) | Werkzeug scrypt hashes of the demo password, so they are valid in the app |
| `incidents` columns | `reference`, `disaster_type`, `severity`, `status`, `description`, `location_id` → `locations`, `reported_by` (nullable), timestamps | `title`, `description`, `incident_type`, `severity`, `status`, `location` (text), `zone_id` → `zones`, `reported_by` (**NOT NULL**), timestamps |
| incident `status` values | lowercase: reported, verified, dispatched, resolved, closed | uppercase: REPORTED, VERIFIED, RESPONDING, RESOLVED, CLOSED, REJECTED |
| incident `severity` values | lowercase low … critical, **already NOT NULL** | uppercase LOW … CRITICAL, default MODERATE |
| other tables | roles, locations, rescue_teams, hospitals, partner_profiles, missions, simulations, audit_entries | zones, response_units, resources, incident_updates, dispatches, resource_allocations |
| migrations | `001` only; `init_db()` re-runs it by splitting on `;` (this would break a PL/pgSQL body) | n/a |
| SQLite | the app falls back to SQLite when `DATABASE_URL` is unset | PostgreSQL only |

## 2. Reconciliation decisions

The prompt assumes migration 002 can `ALTER incidents` and add `severity` / `zone_id`. That is not possible here:
`severity` already exists with a different value set, anonymous public reports are stored with `reported_by = NULL`
(Review II requires NOT NULL), and the existing `PATCH /api/incidents/<id>` moves reports to *verified* without a zone
(Review II forbids that, rule FR-05). Rewriting the legacy table would change registration-adjacent behaviour that must
stay unchanged. The prompt allows the safest option that keeps existing features working, so:

| # | Decision | Why |
|---|---|---|
| D1 | **Review II objects live in a new PostgreSQL schema `response`, inside the application database.** Tables, columns, constraints, functions, procedures, triggers and the view keep their Review II names. Existing tables are untouched. | Zero regression risk for the legacy flows; one database, one transaction scope, real foreign keys to `users`. |
| D2 | The Review II `users` table is **not** duplicated. Every `users(id)` foreign key and every PL/pgSQL reference to `users` resolves to `public.users` (the `response` schema has no `users` table; the schema search path is `response, public`). | A single identity table is the better design to defend in the viva. |
| D3 | `public.users` gets one additive column: `account_type` as a **stored generated column** from `role` (admin → ADMINISTRATOR, official → COORDINATOR, responder → UNIT_LEAD, volunteer and citizen → CITIZEN), plus `ck_users_account_type` with exactly the four Review II values. | Reconciles the label sets without touching `role`, the registration endpoint, the JWT, the partner portals or the UI. The final allowed set is CITIZEN, COORDINATOR, UNIT_LEAD, ADMINISTRATOR, as required. Review II's procedure `sp_dispatch_unit` reads `users.account_type` unchanged. |
| D4 | `ck_users_email_format` is **not** added to `public.users`. | The legacy registration endpoint only requires an `@`; a regex CHECK would reject addresses it accepts today. The format rule is enforced for response-model writes by the API instead. |
| D5 | The response-model endpoints are under **`/api/response/…`** (e.g. `/api/response/incidents/<id>/verify`) rather than `/api/incidents/<id>/verify`. | `/api/incidents` already means the legacy table and its ids; reusing the path would make two id spaces ambiguous. |
| D6 | The migration runner executes each file as a whole (not split on `;`), records versions in `schema_migrations`, and replaces the naive splitter in `init_db()`. Migration 002 is idempotent and also valid when executed by `psql` through `docker-entrypoint-initdb.d` on a fresh volume. | PL/pgSQL bodies contain semicolons. |
| D7 | Two additions that Review II lacks, kept in migration 002 because "rules live in the database": (a) trigger `trg_incidents_transition_guard` (R3-1) rejects illegal status changes such as CLOSED → VERIFIED; (b) procedure `sp_update_dispatch` (R3-2) lets only the unit's lead record EN_ROUTE / ON_SCENE / COMPLETED and releases the unit on completion. Neither changes a Review II object. | Without them, "only the lead of that unit may do it" and "no illegal transition" would be Python rules. (c) Added later in migration 003 for FR-06: trigger `trg_units_lead_type` (R3-3) requires the lead of a response unit to hold a UNIT_LEAD account (Review I, Table 9). It is a separate migration because 002 was already applied to running databases. |
| D8 | PostgreSQL-only: response endpoints return HTTP 501 with a clear message on the SQLite fallback. Existing SQLite tests keep passing. | The procedures, cursors and triggers are PL/pgSQL. |
| D9 | The Review II scripts are copied to `backend/db/review2/` as requested. `docs/review2/sql/` stays because the Compose file and `start-project.ps1` mount it. A test asserts the SQL files in both places are identical. | Avoids breaking the launcher. |
| D10 | Demo data: `flask seed-demo` replays the same 14-incident, 12-unit, 12-resource history as `gen_seed.py`, mapping its 16 people to application users (all with the Review II demo password). Guarded by `DMERS_ALLOW_DEMO_SEED=1`. | Same data and same triggers as Review II; counts are asserted against the Review II execution log. |
| D11 | New dependency `psycopg-pool` (the prompt asks for a pool). PDF export is produced in the browser with `jspdf`, which is already a dependency; no backend PDF library is added. | Fewer moving parts. |
| D12 | Frontend tests use `node --test` for pure modules (trace formatting, CSV/PDF layout, demo script); screens are verified by `vite build` and by driving them in a browser. No new test framework is added. | Matches the repo's existing test style. |
| D13 | Authorisation is checked in Flask from the database's `account_type` (never from the UI); rules about data (unit busy, incident not verified, stock, lead-only, illegal transition) are enforced by PostgreSQL and merely translated to HTTP. | Required by the hard constraints. |

## 3. Existing behaviour that must not change (and how it is proved)

Registration, sign-in, `POST/GET/PATCH /api/incidents`, `/api/public/reports`, `/health` (extended with new keys only),
the AI advisory, hospitals, missions and the Data tab. A regression test file runs the existing flows against a real
PostgreSQL database after migration 002 and asserts the same responses as before. The existing SQLite suite stays green.

## 4. Build order

1. Phase 1: migration 002, runner, `backend/db` access layer, `/health` extension, demo seed.
2. Phase 2: transactions T1–T10 as REST + React. Afterwards, T11 (FR-06, FR-09 administrator maintenance) with migration 003.
3. Phase 3: reports page, CSV and black-and-white PDF.
4. Phase 4: Database activity panel, guided demo, headless demo script and log.
5. Phase 5: tests on a disposable PostgreSQL database, including the concurrent-dispatch test.
6. Phase 6: `docs/review3/*` using only real output.

Each phase is committed separately.
