"""Persistent event log for the operator admin timeline."""

from __future__ import annotations

from enum import IntEnum
from typing import Any, Optional

from .db import get_cursor


class LogLevel(IntEnum):
    DEBUG = 1
    INFO = 5
    IMPORTANT = 10
    NOTIFICATION = 15
    WARNING = 20
    ERROR = 30


LEVEL_LABELS = {
    LogLevel.DEBUG: "DEBUG",
    LogLevel.INFO: "INFO",
    LogLevel.IMPORTANT: "IMPORTANT",
    LogLevel.NOTIFICATION: "NOTIFICATION",
    LogLevel.WARNING: "WARNING",
    LogLevel.ERROR: "ERROR",
}


def write_log(
    component: str,
    title: str,
    text: str = "",
    level: LogLevel = LogLevel.INFO,
    *,
    cur: Optional[Any] = None,
) -> None:
    """Insert a log row. Pass ``cur`` when already inside a DB transaction."""
    sql = """
        INSERT INTO log_messages (component, level, title, text)
        VALUES (%s, %s, %s, %s);
    """
    args = (component, int(level), title, text or "")
    if cur is not None:
        cur.execute(sql, args)
        return
    with get_cursor(commit=True) as (_conn, c):
        c.execute(sql, args)
