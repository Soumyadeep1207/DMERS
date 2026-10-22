"""A lazily created psycopg connection pool bound to DATABASE_URL.

Connections use the search path ``response, public`` so the unqualified table names in the
Review II SQL (incidents, zones, dispatches, ...) resolve to the incident-response schema while
``users`` resolves to public.users.
"""
from __future__ import annotations

import os
import threading

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

SEARCH_PATH = "response,public"
_lock = threading.Lock()
_pool: ConnectionPool | None = None
_pool_url: str | None = None
_pool_pid: int | None = None     # a pool must never be shared across a fork (gunicorn --preload)


def database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def available() -> bool:
    return bool(database_url())


def get_pool() -> ConnectionPool:
    """Return the shared pool, creating it (or recreating it when DATABASE_URL changed)."""
    global _pool, _pool_url, _pool_pid
    url = database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not configured; the response model needs PostgreSQL")
    with _lock:
        if _pool is not None and _pool_pid != os.getpid():
            _pool = None            # inherited from the parent process: its sockets belong to the parent, so drop it, never close it
        if _pool is not None and _pool_url != url:
            _pool.close()
            _pool = None
        if _pool is None:
            _pool = ConnectionPool(
                url, min_size=1, max_size=int(os.getenv("DMERS_DB_POOL_MAX", "8")), open=True, name="dmers-response",
                kwargs={"row_factory": dict_row, "options": f"-c search_path={SEARCH_PATH}"},
            )
            _pool_url, _pool_pid = url, os.getpid()
        return _pool


def close_pool() -> None:
    global _pool, _pool_url, _pool_pid
    with _lock:
        if _pool is not None and _pool_pid == os.getpid():
            _pool.close()
        _pool, _pool_url, _pool_pid = None, None, None
