# DMERS Review II database integration

The Review II database is integrated as a second database in the project's PostgreSQL container. The application continues to use `dmers`; the Review II schema and its demonstration data live in `dmers_course`. This separation preserves the existing application tables while making the Review II functions, procedures, cursor, triggers, queries and constraints available to the command-centre demo.

The source report is in this folder. The complete SQL package is in `sql/`. Docker mounts the SQL directory read-only at `/review2`. The project launcher creates `dmers_course` if needed, runs `run_all.sql` once when the schema is absent, then starts Flask and the frontend. It does not reset a populated course database during ordinary application startup.

## Live application access

- Frontend: `http://127.0.0.1:5175`
- Backend and combined database health: `http://127.0.0.1:5003/health`
- Review II API health: `http://127.0.0.1:5003/api/health`
- Review II live data API: `GET /api/review2/overview` (requires an application bearer token)
- PostgreSQL host and port: `127.0.0.1:5433`
- Application database: `dmers`
- Review II database: `dmers_course`
- PostgreSQL user: `dmers`
- PostgreSQL password: the local `POSTGRES_PASSWORD` value in the project-root `.env`

Use `docker compose exec -T postgres psql -U dmers -d dmers_course` to open the Review II database from PowerShell without putting its password in shell history. The SQL demo accounts are fictional: `meena.krishnan@dmers.example.org` (administrator) and `rajesh.subramanian@dmers.example.org` (coordinator); their shared demo password is `Dmers@2026`. These are coursework-database records, not application sign-in credentials.

## Re-run the SQL demonstrations

The normal launcher preserves existing `dmers_course` records. To explicitly rebuild the coursework demo, run from the project root:

```powershell
docker compose exec -T postgres psql -U dmers -d dmers_course -v ON_ERROR_STOP=1 -f /review2/run_all.sql
```

`00_reset.sql` drops the Review II objects in the database to which psql is connected. Its guard refuses to run in the application database named `dmers`. The script includes negative constraint tests; their expected SQL errors are part of the demonstration.
