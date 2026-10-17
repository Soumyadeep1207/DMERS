#!/bin/sh
set -eu

: "${PGHOST:?PGHOST is required}"
: "${PGUSER:?PGUSER is required}"
: "${PGPASSWORD:?PGPASSWORD is required}"
: "${APP_DB_PASSWORD:?APP_DB_PASSWORD is required}"
: "${APP_DB_USER:?APP_DB_USER is required}"

export PGPORT="${PGPORT:-5432}"
export PGSSLMODE="${PGSSLMODE:-require}"

until pg_isready --host "$PGHOST" --port "$PGPORT" --username "$PGUSER" --dbname postgres; do
  echo "Waiting for the private RDS PostgreSQL instance..."
  sleep 3
done

# Create a restricted application role; the RDS master account is only used by
# this one-off bootstrap task, never by the running web services.
psql --host "$PGHOST" --username "$PGUSER" --dbname postgres --set ON_ERROR_STOP=1 \
  --set=app_password="$APP_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE dmers_app LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dmers_app')
\gexec
SQL

psql --host "$PGHOST" --username "$PGUSER" --dbname dmers --set ON_ERROR_STOP=1 \
  --command 'GRANT CONNECT, CREATE ON DATABASE dmers TO dmers_app; GRANT USAGE, CREATE ON SCHEMA public TO dmers_app;'

course_exists="$(psql --host "$PGHOST" --username "$PGUSER" --dbname postgres --tuples-only --no-align \
  --command "SELECT 1 FROM pg_database WHERE datname = 'dmers_course'")"
if [ "$course_exists" != "1" ]; then
  psql --host "$PGHOST" --username "$PGUSER" --dbname postgres --set ON_ERROR_STOP=1 \
    --command 'CREATE DATABASE dmers_course'
fi

psql --host "$PGHOST" --username "$PGUSER" --dbname dmers_course --set ON_ERROR_STOP=1 \
  --command 'GRANT CONNECT, CREATE ON DATABASE dmers_course TO dmers_app; GRANT USAGE, CREATE ON SCHEMA public TO dmers_app;'

schema_exists="$(psql --host "$PGHOST" --username "$PGUSER" --dbname dmers_course --tuples-only --no-align \
  --command "SELECT to_regclass('public.resource_allocations') IS NOT NULL")"
if [ "$schema_exists" = "t" ]; then
  echo "Review II database already exists; leaving its data unchanged."
else
  echo "Initializing the separate Review II coursework database..."
  PGPASSWORD="$APP_DB_PASSWORD" psql --host "$PGHOST" --username "$APP_DB_USER" --dbname dmers_course --set ON_ERROR_STOP=1 \
    --file /migrations/run_all.sql
fi

echo "Course database bootstrap completed."
