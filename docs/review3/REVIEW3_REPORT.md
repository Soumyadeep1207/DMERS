# DMERS Review III: Integrated System and Final Demonstration (BCSE302L)

## 1. Project title and team

**DMERS: Disaster Management and Emergency Response System, Incident-Response Database**

| Name | Registration number |
|---|---|
| Vighnesh Das | 24BYB0153 |
| Soumyadeep Chowdhury | 24BYB0175 |

Stack: PostgreSQL 16, Flask with psycopg 3 and psycopg_pool, React, Docker Compose. Every output quoted below comes from a real run (`demo_run_log.txt`,
`report_outputs.md`, the test suites); nothing is mocked.

## 2. Introduction and problem statement

During a disaster, reports arrive from the public, coordinators must verify them, dispatch the right unit, supply relief and later explain who did what.
The database must keep this consistent when many people act at once: a unit must never be sent to two incidents, stock must never go negative,
and the history must not be rewritable. Reviews I and II designed and tested that database as SQL scripts. Review III integrates it into the running application so that
every user operation is one database transaction, the database enforces the rules, and the examiner can see the database work.

## 3. Functional requirements

Quoted from Review I, Table 7 (the actor is in brackets). The last column shows how Review III exercises each requirement.

| ID | Requirement (Review I) | In Review III |
|---|---|---|
| FR-01 | Register an account with name, account type, e-mail and password; reject a duplicate e-mail (Citizen, Administrator) | T1, existing endpoint with a `db_trace`; UNIQUE e-mail, step 2 of the log |
| FR-02 | Sign in with e-mail and password, checked against the stored hash (all users) | T1, existing endpoint; the hash is never returned |
| FR-03 | Report an incident with title, description, type and location; status starts as REPORTED and the first timeline entry is created automatically (Citizen) | T2; trigger `trg_incidents_timeline` writes entry 1 |
| FR-04 | List and filter incidents by status, severity, type and zone (Coordinator) | Response Ops list (status filter), report Active incidents. Filtering by severity, type and zone is not built into the list |
| FR-05 | Verify or reject a report; on verification assign its severity and zone (Coordinator) | T3; CHECK `ck_incidents_zone_when_verified` |
| FR-06 | Maintain zones and response units, including each unit's base zone and lead account (Administrator) | **Not built in Review III.** Zones and units are created by the seed and read by the screens; there is no create or edit screen |
| FR-07 | Dispatch an available unit to a verified incident and record the authorising coordinator; the unit becomes DEPLOYED and the incident RESPONDING (Coordinator) | T4; `sp_dispatch_unit`, `trg_dispatches_guard` |
| FR-08 | Record dispatch progress (en route, on scene, completed) with timestamps (Unit lead) | T5; `sp_update_dispatch`, only the unit's lead |
| FR-09 | Maintain the relief catalogue and restock items (Administrator) | T8 restock is built. **Adding or renaming catalogue items is not** |
| FR-10 | Allocate relief stock to an incident only when enough is available, and reduce the stock by the allocated quantity (Coordinator) | T6, T9; `trg_allocations_stock` |
| FR-11 | Resolve and close an incident: complete its open dispatches and return those units to AVAILABLE (Coordinator) | T7; `sp_close_incident` with its cursor |
| FR-12 | Show the timeline of an incident: each status change with its time and the account responsible (Coordinator; citizen for own reports) | Incident detail timeline, report Incident timeline, report Accountability |
| FR-13 | Produce situation reports: zone-wise incident counts, unit utilisation, low-stock items and average response time (Coordinator, Administrator) | Reports page, nine reports |
| FR-14 | Report database availability through the backend health check (Administrator) | `/health`, extended with migration level, row counts and object checks |

Review I's business rules BR-01 to BR-10 (Table 8) are enforced as planned there: BR-05, BR-07, BR-08 and BR-10 by the Review II procedures, triggers and functions; BR-09 (history cannot be deleted) by `ON DELETE RESTRICT`, shown in step 27 of the log.

## 4. ER diagram

The ER schema is **Figure 1 of the Review I report** (Elmasri and Navathe notation); it is the design this database implements and is not redrawn here. Review I, Table 10, counts six entity types and eight relationship types:

| Construct | Review I |
|---|---|
| Strong entity types (5) | USER, ZONE, INCIDENT, RESPONSE_UNIT, RESOURCE |
| Weak entity type (1) | INCIDENT_UPDATE (owner INCIDENT, partial key `update_no`) |
| Binary 1:1 | LEADS (USER lead, RESPONSE_UNIT) |
| Binary 1:N (5) | REPORTS (USER, INCIDENT), LOCATED_IN (ZONE, INCIDENT), BASED_IN (ZONE, RESPONSE_UNIT), LOGS (USER, INCIDENT_UPDATE), HAS_UPDATE (identifying) |
| Binary M:N | ALLOCATED (INCIDENT, RESOURCE; quantity and time belong to the pair) |
| Ternary M:N:1 | DISPATCHED_TO (INCIDENT, RESPONSE_UNIT, USER as coordinator) |

Derived attributes (not stored): `active_incidents` and `stock_status`, realised as functions (BR-10). The relational form is in Review I, Tables 11 to 14 and in the next section.

## 5. Relational schema

Schema `response` (Review II names); `users` is the application's `public.users` with a derived `account_type`.

| Relation | Primary key | Foreign keys |
|---|---|---|
| users | `id` | none (application table; `account_type` derived from `role`) |
| zones | `id`; unique `zone_name` | none |
| incidents | `id` | `zone_id` zones (RESTRICT), `reported_by` users (RESTRICT) |
| response_units | `id`; unique `unit_name`, unique `lead_user_id` | `zone_id` zones (RESTRICT), `lead_user_id` users (SET NULL) |
| resources | `id`; unique `resource_name` | none |
| incident_updates | `(incident_id, update_no)` | `incident_id` incidents (CASCADE), `logged_by` users (RESTRICT) |
| dispatches | `(incident_id, unit_id)` | incidents, response_units, `dispatched_by` users (all RESTRICT) |
| resource_allocations | `(incident_id, resource_id)` | incidents, resources (RESTRICT) |

## 6. Table creation and constraints

DDL: `backend/migrations/002_incident_response.sql` (generated from `backend/db/review2/01_schema.sql`, same constraint names; applied by the migration runner and also by `psql` on a new volume).
Constraint families (names as in Review II): primary keys `pk_*`; unique `uq_*` (e-mail, zone, unit, resource, one lead per unit); foreign keys `fk_*`; checks `ck_*` for enumerations
(severity, status, unit type, availability, category), formats (`ck_units_phone`), ranges (`ck_resources_quantity`, `ck_allocations_quantity`, `ck_units_personnel`) and cross-column rules
(`ck_incidents_zone_when_verified`, `ck_dispatches_arrival`, `ck_dispatches_cleared_when_closed`, `ck_updates_first_entry`); the partial unique index `uq_dispatches_one_active_per_unit`;
defaults for status, severity, availability and timestamps. Verified by the migration test (001 then 002 on a database with existing rows, 002 applied twice) and by the failure paths below.

## 7. SQL queries and outputs

The fifteen Review II queries are unchanged in `backend/db/review2/05_queries.sql`. Nine of them run inside the application as reports, with the same SQL text and parameters where Review II had literals
(`backend/db/reports.py`). Their output on the reset demonstration data is in [`report_outputs.md`](report_outputs.md). Examples:

**Command board for open incidents** (FR-13, Q14, two CTEs):

| id | severity | on_scene | on_the_way | relief_items |
|---|---|---|---|---|
| 7 | CRITICAL | 2 | 1 | 6 |
| 9 | MODERATE | 0 | 0 | 2 |
| 10 | HIGH | 0 | 0 | 1 |
| 11 | HIGH | 1 | 0 | 0 |
| 14 | HIGH | 1 | 2 | 3 |

**Relief stock status, items at or below the reorder level** (FR-13, Q5, `fn_stock_status`):

| resource_name | available | reorder_level | stock_status |
|---|---|---|---|
| Inflatable rescue boats | 0 | 2 | OUT_OF_STOCK |
| Portable generators | 2 | 3 | LOW |
| Tarpaulin sheets | 50 | 60 | LOW |
| Water purification tablets | 80 | 100 | LOW |

**Average response time per zone** (FR-13, Q10, `AVG(fn_response_minutes)`): Katpadi 16 min (2 incidents), Ambur 21, Gudiyatham 21, Vellore Town 31.5, Sathuvachari 32, Walajapet 54, Pernambut 58.

*Correctness check.* `backend/tests/test_reports.py` builds a second database from the untouched Review II scripts (01, 02, 03), runs the original text of `05_queries.sql` there and requires the application's
reports to return identical rows (nine comparisons pass). The seed reproduces Review II's own row counts: 14 incidents, 61 timeline entries, 16 dispatches, 15 allocations.

## 8. Procedures, functions, cursor and triggers

| Object | Purpose | Exercised by (log step) |
|---|---|---|
| `fn_stock_status` | OUT_OF_STOCK / LOW / ADEQUATE | T8 restock (22), reports |
| `fn_active_incidents` | active incidents in a zone | zone situation report, reference lists |
| `fn_response_minutes` | report to first arrival | response-time report, incident list |
| `sp_dispatch_unit` | dispatch, unit DEPLOYED, incident RESPONDING, NOTICE | T4 (10, 9) |
| `sp_close_incident` + cursor `c_open` | release active units, RESOLVED then CLOSED | T7 (19, 20) |
| `trg_incidents_timeline` (T1) | timeline entry on INSERT and status change | T2 (4), T3 (8), T4, T7 |
| `trg_incidents_touch` (T2) | maintains `updated_at` | T3, T4, T7 |
| `trg_dispatches_guard` (T3) | unit must be AVAILABLE, incident VERIFIED or RESPONDING | T4 (6, 9) |
| `trg_allocations_stock` (T4) | stock moves, over-allocation refused | T6 (15 to 17), T9 (18) |
| `trg_incident_updates_append_only` (T5) | timeline cannot be edited or deleted directly | T10 (28), T9 (26 allows the cascade) |
| Review III: `sp_update_dispatch`, `trg_incidents_transition_guard` | lead-only progress; legal status changes | T5 (11 to 14), T3, T9 |
| view `v_zone_situation` | zone situation | zone situation report |

## 9. Real-world transaction demonstrations

Each transaction is a REST endpoint, a React screen and a database component, and returns a `db_trace`. The five guideline questions are answered live by the **Database activity** drawer and
in `demo_run_log.txt` (28 steps, all behaving as expected on 22 October 2026). Failure paths are part of each demonstration: the whole transaction rolls back and the trace shows every watched value unchanged.

### T1 Register and sign in (log steps 1 to 3)
*Operation:* create an account. *Tables:* `users`, `roles`. *Component:* constraints `users_email_key` (UNIQUE), `users_role_fkey`, derived `account_type` with `ck_users_account_type`.
*Effect:* one row; the password is stored only as a Werkzeug scrypt hash. *Result:* HTTP 201; registering the same address again returns HTTP 409 and rolls back.

### T2 Report an incident (step 4)
*Endpoint:* `POST /api/response/incidents`. *Tables:* `incidents`, `incident_updates`. *Component:* DEFAULTs (REPORTED, MODERATE) and trigger `trg_incidents_timeline`.
*Effect:* 2 rows (1 incident, timeline entry 1 written by the trigger). *Result:* HTTP 201.

### T3 Verify or reject (steps 5 to 8, 25)
*Endpoint:* `POST /api/response/incidents/<id>/verify`. *Component:* UPDATE under `ck_incidents_zone_when_verified`; triggers `trg_incidents_touch`, `trg_incidents_transition_guard`, `trg_incidents_timeline`
(author from `dmers.actor_id`, note from `dmers.note`). *Refused:* a citizen (HTTP 403, step 5); a non-existent zone (`fk_incidents_zone`, step 7).

### T4 Dispatch a unit (steps 6, 9, 10)
Committed (step 10), verbatim from the log:

```
[10] Dispatch Katpadi Fire Unit
      user        : Priya Natarajan (COORDINATOR)
      request     : POST /api/response/incidents/15/dispatch
      result      : HTTP 201 (as expected)
      operation   : Dispatch a unit (COMMITTED, 8.8 ms)
      components  : CALL sp_dispatch_unit, trigger trg_dispatches_guard, trigger trg_incidents_touch, trigger trg_incidents_transition_guard, trigger trg_incidents_timeline
      tables      : dispatches, response_units, incidents, incident_updates
      rows changed: dispatches inserted 1; incident_updates inserted 1; incidents updated 1; response_units updated 1  (total 4)
      NOTICE      : Unit 2 (Katpadi Fire Unit) dispatched to incident 15 by user 9
      Unit              : AVAILABLE -> DEPLOYED   Incident: VERIFIED -> RESPONDING   Timeline: 2 -> 3 entries
```

Refused (step 9): `Unit 9 is DEPLOYED, not AVAILABLE`, components `CALL sp_dispatch_unit, trigger trg_dispatches_guard`, all watched values unchanged (rolled back). Step 6: dispatch before verification is refused by the same trigger.

### T5 Record unit progress (steps 11 to 14)
`PATCH /api/response/dispatches/<incident>/<unit>` calls `sp_update_dispatch`: only the unit's lead, in the order ASSIGNED, EN_ROUTE, ON_SCENE, COMPLETED; arrival time satisfies `ck_dispatches_arrival`.
Refused: a citizen (step 11), jumping to COMPLETED (step 13: `Dispatch cannot move from EN_ROUTE to COMPLETED`).

### T6 Allocate relief (steps 15 to 17)
`INSERT ... ON CONFLICT DO UPDATE` (cumulative: 30 then 20 more gives 50) fires the AFTER trigger `trg_allocations_stock`: 3 rows change (allocation, stock, timeline note). Refused (step 17): an inflatable boat with none in stock,
`Insufficient stock for resource 11: requested 1, available 0`.

### T7 Close an incident (steps 19, 20)
Verbatim from the log:

```
[19] Close the incident
      operation   : Close an incident (COMMITTED, 9.95 ms)
      components  : CALL sp_close_incident, trigger trg_incidents_touch, trigger trg_incidents_transition_guard, trigger trg_incidents_timeline, cursor c_open
      rows changed: dispatches updated 1; incident_updates inserted 2; incidents updated 2; response_units updated 1  (total 6)
      NOTICE      : Unit 2 released (dispatch was ON_SCENE)
      NOTICE      : Incident 15 closed; 1 unit(s) released
      Incident: RESPONDING -> CLOSED   Active dispatches: 1 -> 0   Timeline: 6 -> 8 entries
```

Closing again (step 20) is refused: `Incident 15 cannot be closed from status CLOSED`.

### T8 Restock relief (steps 21 to 23)
`UPDATE resources` then `SELECT fn_stock_status` in a separate statement (a STABLE function sees the snapshot of the statement that calls it). Inflatable boats 0 to 3, status OUT_OF_STOCK to LOW (step 22).
Refused: a coordinator (HTTP 403, step 21); removing more than exists (`ck_resources_quantity`, step 23).

### T9 Withdraw an allocation, delete a duplicate (steps 18, 24 to 27)
Withdrawing fires `trg_allocations_stock` again: stock 300 to 350, timeline note added (step 18). A rejected duplicate is deleted and `ON DELETE CASCADE` removes its timeline (step 26).
Deleting an incident with dispatch history is refused with HTTP 409, constraint `fk_dispatches_incident` (step 27, ON DELETE RESTRICT).

### T10 Edit the timeline (step 28)
`trg_incident_updates_append_only` raises `Timeline entries are append-only (incident 15, update 1)` (SQLSTATE P0001, HTTP 422), even for an administrator.

### Concurrency
`test_concurrent_dispatch_of_one_unit_has_exactly_one_winner`: two simultaneous dispatches of one unit; the results are `[201, 422]` and exactly one active dispatch exists.

## 10. Conclusion

The Review II database is now the working core of the application: users, incidents, units, relief and the audit timeline are served by procedures, a cursor and triggers inside real user transactions,
reports are the Review II queries, and each operation explains itself. Existing features (registration, sign-in, legacy incidents, health) are unchanged and covered by regression tests.

Known limits and open items:
* FR-06 (maintain zones and units) and the catalogue-maintenance part of FR-09 have no screen or endpoint in Review III (section 3); FR-04 lists and filters by status only.
* The ER diagram is Figure 1 of Review I, referenced rather than redrawn (section 4).
* The incident-response endpoints and the demonstration need PostgreSQL; on the SQLite fallback they answer HTTP 501.
* The trace lists BEFORE triggers on a constraint failure by PostgreSQL's firing order rather than by observation (`ARCHITECTURE.md`).
* PDF export was verified by unit tests of its layout; the CSV and the on-screen reports were checked in a browser, the downloaded PDF file itself was not opened.

## Rubric coverage

| Review III criterion | Marks | Where it is satisfied |
|---|---|---|
| Integrated Database Operation | 2 | Migration 002 in the application database; transaction layer `backend/db`; `/health` reports migration level, row counts and the existence of every function, procedure and trigger; `users` shared between application and model; guided demo runs end to end (sections 5, 6, 8; `ARCHITECTURE.md`) |
| Real-World Transactions (at least 5) | 3 | Ten transactions T1 to T10 with success and rollback paths: 28 headless steps and 25 UI steps, `demo_run_log.txt`, section 9 |
| SQL/PLSQL Interaction | 2 | 3 functions, 3 procedures, one explicit cursor, 6 triggers each exercised by at least one transaction and visible in the Database activity drawer (section 8) |
| Output and Reports | 1 | Nine reports with CSV and black-and-white PDF; rows verified against the original Review II queries (section 7, `report_outputs.md`) |
| Project Report and Documentation | 1 | This report, `PLAN.md`, `ARCHITECTURE.md`, `RUN_DEMO.md`, `VIVA_NOTES.md` |
| Viva / Project Understanding | 1 | `VIVA_NOTES.md`; the five-question drawer answers *what, which tables, which component, how affected, what result* for every operation |
