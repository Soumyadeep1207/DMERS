"""DMERS database access layer: pool, transactions, error mapping, migrations, trace and health.

The Review II incident-response model lives in the PostgreSQL schema ``response`` (migration 002).
Every business rule is enforced by the database; this package only runs the statements inside one
transaction per user operation, collects what the database reported, and translates database
errors into HTTP-friendly exceptions.
"""
