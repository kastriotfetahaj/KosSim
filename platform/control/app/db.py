from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor


DEFAULT_DATABASE_URL = "postgresql://kossim:kossim@postgres:5432/kossim"


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def get_connection():
    return psycopg2.connect(get_database_url())


@contextmanager
def get_cursor(commit: bool = False) -> Generator[Tuple[object, object], None, None]:
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield conn, cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
