# DMERS Incident-Response Database — Review II scripts (BCSE302L)

PostgreSQL 16, PL/pgSQL, psql. Team: Vighnesh Das (24BYB0153), Soumyadeep Chowdhury (24BYB0175).

## Run

The scripts use their own database, `dmers_course`. `00_reset.sql` refuses to run in the
application database `dmers`, so the Flask backend's tables are never touched.

With the project's Docker Compose database (host port 5433, user `dmers`):

```
psql -h 127.0.0.1 -p 5433 -U dmers -d dmers -c "CREATE DATABASE dmers_course"
psql -h 127.0.0.1 -p 5433 -U dmers -d dmers_course -f run_all.sql
```

`run_all.sql` can be run again at any time: `00_reset.sql` removes every object first.
`execution_log.txt` is the output of one complete run on a new database.

## Files (run in this order)

| File | Contents |
|---|---|
| 00_reset.sql | Drops every Review II object so the scripts can be re-run |
| 01_schema.sql | 8 tables: primary, foreign, unique and check constraints, defaults, indexes |
| 02_plpgsql.sql | 3 functions, 2 procedures (one with an explicit cursor), 5 triggers |
| 03_seed_data.sql | Reference data, then the incidents of 1–12 Oct 2026 replayed in time order |
| 04_dml_demo.sql | INSERT, UPDATE and DELETE demonstrations |
| 05_queries.sql | The 15 queries Q1–Q15 |
| 06_plpgsql_demo.sql | Calls to the functions and procedures; the cursor and triggers at work |
| 07_constraint_tests.sql | 14 statements that the constraints must reject (K1–K14) |
| tools/gen_seed.py | Generator of 03_seed_data.sql (needs Python 3 and werkzeug) |

## Notes

- All people, e-mail addresses and phone numbers are fictitious. Every demo account's
  password is `Dmers@2026`; only its Werkzeug scrypt hash is stored.
- The triggers read two transaction settings that the procedures set:
  `dmers.actor_id` (the official making a change) and `dmers.note` (text for the next
  timeline entry). An application sets them with `SET LOCAL dmers.actor_id = '3'`.
- `06` and `07` contain statements that are meant to fail; `run_all.sql` turns
  ON_ERROR_STOP off before them so the errors are printed and the run continues.
