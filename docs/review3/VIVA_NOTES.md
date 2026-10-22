# Viva notes: likely questions and answers grounded in this code

Short answers first; the file or object to point at is in brackets.

## The workflow in one breath

A user acts in the React screen, Flask checks who they are, then opens **one transaction** that names the acting user (`set_config('dmers.actor_id', ..., true)`),
runs a parameterised statement or a stored procedure, lets the triggers act, and commits or rolls back. The response returns the result and a `db_trace`
that answers the five guideline questions. [`backend/db/tx.py`, `backend/app/response_api.py`]

## Normalisation and keys

**Is the schema normalised?** Yes, to 3NF/BCNF. Derived values are not stored: stock status (`fn_stock_status`), active incidents per zone
(`fn_active_incidents`), response minutes (`fn_response_minutes`) and the zone situation (view `v_zone_situation`) are computed. `incident_updates` is a weak entity with
composite key `(incident_id, update_no)`; `dispatches` is a ternary relationship keyed `(incident_id, unit_id)` with `dispatched_by` as the authorising official;
`resource_allocations` is an M:N relationship keyed `(incident_id, resource_id)`. [`backend/db/review2/01_schema.sql`]

**Why is `account_type` a generated column in `users`?** The application already stores `role`. A stored generated column derives the Review II type from it, so there is one source of
truth, no update anomaly, and the existing registration and sign-in code did not change. [`002_incident_response.sql`]

**Natural or surrogate keys?** Surrogate `INTEGER GENERATED ALWAYS AS IDENTITY` keys for entities; composite natural keys for the relationship tables, which makes duplicates impossible by construction
(`pk_dispatches` stops the same unit being dispatched twice to one incident).

## ON DELETE actions

| Foreign key | Action | Why |
|---|---|---|
| `incident_updates.incident_id` | CASCADE | A timeline has no meaning without its incident |
| dispatches, allocations to incidents, resources, units | RESTRICT | History must not vanish; `DELETE /api/response/incidents/<id>` returns HTTP 409 (`fk_dispatches_incident`) |
| `incidents.reported_by`, `dispatched_by`, `logged_by` | RESTRICT | Accountability: a person who acted cannot be deleted |
| `response_units.lead_user_id` | SET NULL | A unit survives without its lead |

Demonstrated: step 26 deletes a rejected duplicate (cascade removes its timeline), step 27 is refused (RESTRICT). [`docs/review3/demo_run_log.txt`]

## Trigger timing

**BEFORE or AFTER, and why?** BEFORE triggers can refuse or change the row: `trg_dispatches_guard` (BEFORE INSERT), `trg_incidents_touch` (BEFORE UPDATE), `trg_incidents_transition_guard` (BEFORE UPDATE OF status),
`trg_incident_updates_append_only` (BEFORE UPDATE OR DELETE). AFTER triggers need the final row and write other tables: `trg_incidents_timeline` and `trg_allocations_stock`.
Within a timing PostgreSQL fires triggers in name order. **Why is the append-only trigger allowed at depth greater than one?** `pg_trigger_depth() > 1` means the delete is a cascade from deleting
the incident, which is legitimate; a direct delete of a timeline row is refused (step 28, SQLSTATE P0001).

## Cursor, FOR UPDATE and WHERE CURRENT OF

`sp_close_incident` declares `c_open` over the active dispatches of the incident `FOR UPDATE`. Each `FETCH` locks the row; `UPDATE ... WHERE CURRENT OF c_open` changes exactly that row, avoiding a second lookup and
any race. Per row it decides COMPLETED (was ON_SCENE) or CANCELLED, frees the unit and raises a NOTICE. The notices come back to the browser (step 19: `Unit 2 released (dispatch was ON_SCENE)`, `Incident 15 closed; 1 unit(s) released`).
**Why not one UPDATE?** The outcome and the message depend on each row's previous status, and the unit has to be freed too.

## Transactions, atomicity and rollback

**What makes an operation atomic?** `with conn.transaction()` in `db.tx.transaction`: any exception, whether a CHECK, a trigger's RAISE EXCEPTION or a procedure's, rolls back every statement, including rows written by
triggers. Proof: `test_failure_paths_roll_everything_back` snapshots row counts and stock before and after twelve different failures and asserts they are identical; the trace of a failure shows each watched value as
*unchanged (rolled back)*.

**What isolation level?** PostgreSQL's default READ COMMITTED. It is enough because the guard trigger takes `SELECT ... FOR UPDATE` on the unit row first.

## Preventing a double dispatch

Two defences: `trg_dispatches_guard` locks the unit row `FOR UPDATE` and refuses a unit that is not AVAILABLE (BR-05), and the partial unique index `uq_dispatches_one_active_per_unit` is a backstop that allows at most one
ASSIGNED/EN_ROUTE/ON_SCENE dispatch per unit. `test_concurrent_dispatch_of_one_unit_has_exactly_one_winner` starts two threads on a barrier dispatching the same unit to two incidents: results are always `[201, 422]`.

## STABLE functions and the restock step

**Why is `fn_stock_status` read in a separate SELECT after the UPDATE?** A STABLE function sees the snapshot taken when the statement that calls it starts. Called inside the same statement as the `UPDATE`,
it would report the old quantity. The route runs `UPDATE ... RETURNING` and then `SELECT fn_stock_status(id)` in the same transaction; step 22 shows boats going from 0 (OUT_OF_STOCK) to 3 (LOW).

## Who may do what

Account type is read from the database for each request; a citizen's attempt to verify is refused with HTTP 403 before any SQL runs (step 5). Rules about data are in PostgreSQL: only the lead of a unit may advance its dispatch
(`sp_update_dispatch`, step 11), and only a coordinator may dispatch (`sp_dispatch_unit` checks `account_type`).

## SQL injection

Every statement is parameterised with psycopg placeholders; the transaction layer composes the few identifiers it needs with `psycopg.sql.Identifier`, and only for names from fixed lists (known procedures, report columns).
Trace statements show placeholders, never values. `test_sql_injection_text_is_stored_literally` stores `x'); DROP TABLE response.incidents; --` as a title and checks the table and text are intact.

## Why the design differs from the first plan

The deployed `incidents` table could not be altered in place without changing existing behaviour, so the Review II model lives in schema `response` in the same database and shares `users`. [`docs/review3/PLAN.md`, D1 to D3]

## Traps to avoid in the demo

* Do not claim the trigger list on a failed constraint was observed; it follows PostgreSQL's firing order (see `ARCHITECTURE.md`).
* Seeded history leaves SDRF Team Alpha deployed at incident 7, the boats out of stock and Katpadi Fire Unit as the only available unit that has a lead. The failure steps rely on exactly that, so use **Reset demonstration data** first.
