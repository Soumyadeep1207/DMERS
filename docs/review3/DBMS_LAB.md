# Database laboratories: what PostgreSQL does for DMERS beyond storing rows

Nine additions to the running system, each a migration (005-012), an API under `/api/response/lab/*`, a panel in **Response Ops > Database lab**, and tests in `backend/tests/test_dbms_lab.py` and `frontend/tests/dbLab.test.js`. Every number quoted here is copied from [`dbms_lab_outputs.md`](dbms_lab_outputs.md), which is produced by `python -m db.tools.lab_demo` against the running stack (see RUN_DEMO.md, section 8). Timings are from one machine on one day; compare ratios and plan shapes, not milliseconds.

The OS-laboratory ideas are deliberately not part of this work.

| # | Idea | Migration | Main database objects | Panel |
|---|---|---|---|---|
| 1 | Tamper-evident timeline | 005 | `pgcrypto`, `incident_updates.prev_hash/row_hash`, `trg_incident_updates_chain`, `fn_timeline_hash`, `fn_verify_timeline`, `fn_anchor_timelines`, `timeline_anchors` | 1 Integrity |
| 2 | Row-level security | 006 | role `dmers_rls`, 10 policies (an 11th on `unit_reservations` comes with 007), `fn_actor_id`, `fn_actor_type`, column grants on `users` | 2 Access control |
| 3 | Isolation-level anomalies | 008 | schema `lab`: `stock`, `oncall`, `tickets` (scratch data) | 3 Isolation |
| 4 | Range reservations | 007 | `unit_reservations`, `EXCLUDE USING gist` `ex_reservations_no_overlap`, `fn_unit_free_windows` | 4 Reservations |
| 5 | Routing in the database | 009 | schema `routing`, `cube` + `earthdistance`, GiST KNN, `fn_closed_edges`, `fn_route` (A*), `fn_dispatch_candidates` | 5 Routing |
| 6 | Query-optimiser lab | 010 | `lab.incident_events_flat`, `lab.incident_events` (monthly partitions), BRIN/B-tree variants, `lab.mv_zone_month`, `fn_load_events` | 6 Query optimiser |
| 7 | LISTEN/NOTIFY push | 012 | `trg_incidents_notify`, `trg_dispatches_notify`, channel `dmers_events`, `GET /api/response/stream` | 7 Live push (and the "live" chip in Operations) |
| 8 | In-database analytics | 011 | `lab.fn_zone_daily_zscores`, `lab.fn_zone_forecast` | 8 Analytics |
| 9 | Privacy-safe export | 011 | `lab.fn_public_export` | 9 Privacy |

Decision recorded for idea 5: **PostGIS and pgRouting were not adopted.** They would replace the `postgres:16-alpine` image under the existing data volume; a change of operating-system libc under an existing cluster can invalidate text-sorted indexes, and the stack's value is that `docker compose up` keeps working with existing data. `cube` and `earthdistance` ship with the current image and cover nearest-neighbour search; the search itself is PL/pgSQL.

## 1. Tamper-evident timeline

**Problem.** `trg_incident_updates_append_only` (T5) refuses `UPDATE`/`DELETE` through SQL, but a superuser can run `SET session_replication_role = replica` and edit history with no trigger firing.

**Mechanism.** Each entry stores `row_hash = SHA-256(prev_hash || incident | update_no | previous_status | new_status | note | logged_by | logged_at)`, written by a `BEFORE INSERT` trigger, and `prev_hash` is the previous entry's `row_hash`. `fn_verify_timeline()` recomputes the chain with window functions and reports, per incident, the first entry that is wrong and why (content changed, link broken, numbering gap). `fn_anchor_timelines()` records the current head of every chain so that removing the newest entries is also detected. Entries that existed before migration 005 were sealed in the migration (the append-only trigger is paused for that backfill only).

**Evidence** (run log, section 1). Before the attack: 0 broken chains. After `POST /lab/chain/tamper` rewrote entry 2 of incident 1 (trigger bypass; the trace lists no trigger): incident 1 reported "entry content was changed", first bad entry 2, entries 1, 3 and 4 still individually valid. After restoring the original wording: 0 broken. Tests: `test_tampering_is_detected_and_pinpointed_then_restored`, `test_anchoring_makes_truncation_detectable`, `test_normal_sql_still_cannot_edit_the_timeline_and_new_entries_extend_the_chain`.

**Limits.** Evidence, not prevention. Someone who can rewrite the whole chain and recompute every hash is not stopped; truncation is only detected for anchored heads, so anchors should be published outside the database.

## 2. Row-level security

**Mechanism.** The NOLOGIN role `dmers_rls` is subject to policies that read `current_setting('dmers.actor_id')`, the same session variable the audit triggers use. `fn_actor_type()` is `SECURITY DEFINER` so the restricted role learns only the acting user's account type. Column privileges give `dmers_rls` `SELECT (id, name, role, account_type)` on `users`, never the password hash. The application's own role owns the tables and RLS is enabled, not forced, so every existing flow is unchanged (the full pre-existing suite still passes).

**Evidence** (run log, section 2; identical SQL per column): a citizen sees 3 of 15 incidents and 21 of 69 timeline entries, no dispatches and no allocations; a coordinator and an administrator see all 15/69/17; a unit lead sees no allocations; no signed-in user sees nothing; `SELECT password FROM public.users` is refused with 42501 for everyone; `UPDATE incidents` changes 0 rows for a citizen and 15 for a coordinator; reporting an incident as somebody else is refused with 42501 (`WITH CHECK`). Test: `test_row_level_security_filters_rows_without_a_where_clause`.

**Limits.** The API itself does not yet connect as `dmers_rls`; authorisation in Flask remains the first line and these policies are demonstrated defence in depth. `dmers.actor_id` is set by the application, so an attacker who can run arbitrary SQL could set it too.

## 3. Isolation-level anomalies

**Mechanism.** `db/lab/isolation.py` opens two real sessions, runs a fixed interleaving against scratch tables, and records each statement's result or SQLSTATE. Levels and scenarios are fixed lists; no user text reaches SQL.

**Evidence** (run log, section 3, naive application code):

| Anomaly | READ COMMITTED | REPEATABLE READ | SERIALIZABLE |
|---|---|---|---|
| Lost update | anomaly | prevented (40001) | prevented (40001) |
| Write skew | anomaly | anomaly | prevented (40001) |
| Phantom read | anomaly | no anomaly | no anomaly |
| Non-repeatable read | anomaly | no anomaly | no anomaly |

With `SERIALIZABLE` and a retry loop the write-skew scenario ends with one medic on duty: session B's `COMMIT` fails with 40001 (`could not serialize access due to read/write dependencies`), B retries, sees one medic on duty and does nothing. Tests: `test_isolation_matrix_matches_postgresql_behaviour`, `test_lost_update_and_its_two_cures`, `test_write_skew_is_stopped_only_by_serializable_and_retry_restores_the_rule`.

**Note.** PostgreSQL's REPEATABLE READ is snapshot isolation (stronger than the SQL standard's, but it still allows write skew). READ UNCOMMITTED behaves as READ COMMITTED, so it is not offered.

## 4. Range reservations with an exclusion constraint

**Mechanism.** `EXCLUDE USING gist (unit_id WITH =, period WITH &&) WHERE (status = 'BOOKED')` on a `tstzrange`. Ranges are half-open `[start, end)`, so a booking may start when another ends. `fn_unit_free_windows` subtracts the booked ranges from a window using multirange arithmetic. SQLSTATE 23P01 is mapped to HTTP 409 with the constraint name.

**Evidence** (run log, section 4): booking 08:00-20:00 succeeds (201); 19:00-02:00 for the same unit is refused (409, `ex_reservations_no_overlap`, 23P01, transaction rolled back); 20:00-22:00 succeeds (touching ranges). `test_two_simultaneous_bookings_exactly_one_wins` holds one insert uncommitted, starts a second in another connection, asserts the second is **waiting**, commits the first, and asserts the second then fails with `ExclusionViolation`.

**Limit.** Reservations are independent of dispatching: `sp_dispatch_unit` does not yet refuse a unit that is in a MAINTENANCE booking.

## 5. Routing inside the database

**Mechanism.** The offline OpenStreetMap graph (16,352 nodes, 35,388 segments, 68 facilities) is loaded into schema `routing` by `db/lab/road_loader.py`, using the same projection and travel-time formula as `road_network.py`. Nearest road node and nearest facility are GiST k-nearest-neighbour scans on `earth` points. `fn_closed_edges` closes a segment when a block lies within 35 m of the real segment. `fn_route` is A* in PL/pgSQL with straight-line time at the fastest speed as the admissible heuristic. The API runs the same question through the Python search and compares.

**Evidence** (run log, section 5), Vellore Fire station to A.S.A Hospital: both engines 9.64 min, 5.823 km, 128 segments (5,104 vs 5,117 nodes expanded, a tie-breaking difference). With a road block mid-route: both close 8 segments and both return 9.76 min, 6.151 km, 147 segments. Run time: PostgreSQL about 2.5 s, Python about 9 ms. Tests: `test_database_route_equals_the_python_route`, `test_road_block_closes_segments_in_both_implementations`, `test_a_facility_on_the_incident_node_has_zero_driving_time` (a regression test for a bug found while building the panel: a facility on the incident's own node returned NULL instead of 0).

**Limits.** Parity is exact for road blocks only; the Python layer's fire/flood exposure weighting and weather speeds are not duplicated in SQL. Python is about 270 times faster here: the value of the database version is one source of truth next to the data, not speed. In the one nearest-hospital example in the run log the straight-line order and the driving order agree (CMC, Fathima, Gita Mathai); the panel reports both ranks so a case where they differ would show.

## 6. Query-optimiser laboratory

**Mechanism.** `lab.fn_load_events(n)` generates `n` synthetic incidents (deterministic seed, time-ordered, with three planted surges) into a heap table and a monthly range-partitioned copy. Each run drops the lab indexes, builds the variant's index **inside a transaction**, runs `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` with parallel workers off, reads the answer, and rolls back, so no index remains. The UI draws the plan tree with per-node time bars.

**Evidence** (run log, section 6, 200,150 rows):

| Experiment | Variant | Execution ms | Plan |
|---|---|---|---|
| Open incidents in one zone | no index | 14.85 | Seq Scan, 2,015 buffers |
| | B-tree (zone_id, status) | 1.531 | Bitmap Heap Scan |
| Incidents in one week | no index | 9.406 | Seq Scan |
| | B-tree on occurred_at | 0.556 | Index Only Scan, index 4,513,792 B |
| | BRIN on occurred_at | 1.349 | Bitmap Heap Scan, index 24,576 B |
| | monthly partitions | 1.201 | 1 partition scanned |
| Monthly totals per zone | GROUP BY over the table | 117.819 | Seq Scan |
| | materialised view | 0.805 | reads `lab.mv_zone_month` |

Test `test_experiments_need_history_and_leave_no_index_behind` also asserts every variant returns the same answer and that no `ix_flat_*` index survives.

**Limits.** BRIN works here only because rows were loaded in time order. The real `incident_updates` table is not partitioned (small, append-only, referenced by foreign keys). The materialised view must be refreshed when history changes.

## 7. LISTEN / NOTIFY push

**Mechanism.** After-row triggers call `pg_notify('dmers_events', json)` with ids and statuses only. PostgreSQL delivers a notification when the transaction commits and discards it on rollback. `GET /api/response/stream` (coordinators, unit leads, administrators) holds a dedicated connection that `LISTEN`s and relays messages as server-sent events with 15-second keep-alives; at most 6 streams per server process (`DMERS_MAX_STREAMS`). The browser uses `fetch` streaming because it must send the `Authorization` header. The Operations list refreshes when a message arrives; it does not poll.

**Evidence.** Run log, section 7: reporting and verifying an incident produced exactly two messages (`INSERT ... REPORTED`, `UPDATE ... VERIFIED`) on the stream. Tests: `test_a_committed_change_is_pushed_and_a_rolled_back_one_is_not` (an `UPDATE` rolled back publishes nothing), `test_dispatch_is_pushed_and_the_stream_endpoint_is_role_guarded`. Verified in the browser: with the Live push tab open, a coordinator's report and verify appeared as two lines within the second.

**Limit.** NOTIFY is not queued for disconnected listeners: a client that reconnects must refetch (the Operations screen does).

## 8. In-database analytics

**Mechanism.** `fn_zone_daily_zscores(window, threshold)` builds a zone-by-day grid, counts events, and applies `avg()`/`stddev_samp()` over `ROWS BETWEEN window PRECEDING AND 1 PRECEDING`; a day is a spike when its z-score reaches the threshold. `fn_zone_forecast` fits `regr_slope`/`regr_intercept`/`regr_r2` over the last 28 days and sums the next 7 fitted days.

**Evidence** (run log, section 8; threshold 6): the three planted surges rank first: Vellore Town 2025-11-10 (73 incidents, trailing mean 21.64, z 12.56), Katpadi 2026-03-04 (69, z 10.55), Sathuvachari 2026-08-19 (68, z 9.26). Test `test_planted_surges_are_the_top_spikes_and_match_a_python_calculation` recomputes one z-score and one regression slope independently in Python and compares.

**Limits.** At a low threshold the method also flags chance spikes (on a 100,000-row scratch run at threshold 3, unplanted days appeared among the top six); the UI defaults to 5. R-squared values in the run are 0.004 to 0.049, i.e. the linear trend explains almost nothing for this synthetic data, and the panel says so. The data is synthetic.

## 9. Privacy-safe export

**Mechanism.** `fn_public_export(source, k, epsilon, seed)` counts incidents per zone, type and month. Without `epsilon`, cells with a true count below `k` are suppressed. With `epsilon`, Laplace noise of scale `1/epsilon` (counting query, sensitivity 1) is added to every count first and the `k` threshold is applied to the noisy count. Citizens and others receive only the released column; administrators also see true counts and the error.

**Evidence** (run log, section 9, 2,731 cells): k=5 exact: 1 cell suppressed; k=5 with epsilon 1: mean absolute error 0.986 per cell; epsilon 0.2: 5.098 per cell (about 1/epsilon, as Laplace theory predicts); k=40 exact: 251 cells (9.2%) suppressed. The 14 live incidents with k=5: 100% of cells suppressed and no `true_count` in the response. Tests cover suppression, reproducibility with a seed, error scaling with epsilon, and the citizen view.

**Limits.** Suppression alone does not stop differencing between overlapping releases; epsilon accumulates across repeated releases and the system does not track a privacy budget.

## Honest summary of what is and is not done

* All nine ideas run against the real database with tests. The nine panels were opened in the browser; routing, optimiser and live push were driven end to end.
* Not done: running the API as `dmers_rls`; making `sp_dispatch_unit` respect reservations; a privacy-budget ledger; the "observability" idea (lock waits and buffer-cache hit rates in `db_trace`), which is operating-system flavoured and belongs with the later OS discussion.
