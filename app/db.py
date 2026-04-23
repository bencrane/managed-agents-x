"""Database connection helper.

Uses SUPABASE_DB_URL (the direct Postgres connection string from Doppler).
Keeps psycopg usage explicit so the app stays Supabase-port-agnostic.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg

from app.config import require


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    dsn = require("supabase_db_url")
    with psycopg.connect(dsn, autocommit=False) as conn:
        yield conn
