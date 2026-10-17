-- =====================================================================================
-- DMERS Incident-Response Database | BCSE302L Review II
-- run_all.sql : builds the course database and runs every demonstration in order.
-- Usage:  psql -d dmers_course -f run_all.sql      (see README.md; never use the app DB "dmers")
-- =====================================================================================
\set ON_ERROR_STOP on
\set QUIET on
\echo '== 00-03: reset, tables and constraints, PL/pgSQL objects, demonstration data'
\ir 00_reset.sql
\ir 01_schema.sql
\ir 02_plpgsql.sql
\ir 03_seed_data.sql
\set QUIET off
\set ECHO queries
\echo '== 04: INSERT, UPDATE and DELETE'
\ir 04_dml_demo.sql
\echo '== 05: fifteen queries'
\ir 05_queries.sql
\set ON_ERROR_STOP off
\echo '== 06: functions, procedures, cursor and triggers (three calls and two edits are meant to fail)'
\ir 06_plpgsql_demo.sql
\echo '== 07: constraint tests (every statement is meant to fail and nothing is changed)'
\ir 07_constraint_tests.sql
