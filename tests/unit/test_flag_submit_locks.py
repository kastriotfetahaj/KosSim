"""Tests for the advisory-lock helpers in flag_submit.

These cover the race-condition fixes for:
- round-limit counter (`_serialize_submitter`)
- firstblood determination across submitters (`_resolve_firstblood`)

A small FakeCursor records every executed statement so we can assert the
exact SQL pattern (advisory locks must be issued, with the right key
shape) without spinning up a real Postgres.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest

from ksapp.flag_submit import _resolve_firstblood, _serialize_submitter


class FakeCursor:
    """Minimal psycopg2-style cursor that returns canned RealDict rows."""

    def __init__(self, responses: Optional[List[Dict[str, Any]]] = None) -> None:
        self.queries: List[Tuple[str, Tuple[Any, ...]]] = []
        self._responses: List[Dict[str, Any]] = list(responses or [])
        self._last_row: Optional[Dict[str, Any]] = None

    def execute(self, sql: str, params: Tuple[Any, ...] = ()) -> None:
        self.queries.append((sql, tuple(params) if params else ()))
        # Pop the next canned response; default to None ("no row").
        self._last_row = self._responses.pop(0) if self._responses else None

    def fetchone(self) -> Optional[Dict[str, Any]]:
        return self._last_row


# ---------------------------------------------------------------------------
# _serialize_submitter
# ---------------------------------------------------------------------------


def test_serialize_submitter_issues_advisory_lock():
    cur = FakeCursor()
    _serialize_submitter(cur, submitter_id=42)
    assert len(cur.queries) == 1
    sql, params = cur.queries[0]
    assert "pg_advisory_xact_lock" in sql
    assert params == (42,)


def test_serialize_submitter_coerces_int():
    """Defensive: callers may pass an int-like, but the lock arg must be a
    plain Python int so psycopg2 binds it as int4/int8."""
    cur = FakeCursor()
    _serialize_submitter(cur, submitter_id="7")  # type: ignore[arg-type]
    _, params = cur.queries[0]
    assert params == (7,)


# ---------------------------------------------------------------------------
# _resolve_firstblood
# ---------------------------------------------------------------------------


def test_resolve_firstblood_returns_true_when_first():
    """Lock acquired AND no prior acceptance → firstblood."""
    cur = FakeCursor(
        responses=[
            {"got": True},  # pg_try_advisory_xact_lock
            None,           # SELECT 1 ... (no rows)
        ]
    )
    assert _resolve_firstblood(cur, target_team_id=2, service_id=5) is True
    # First call must be the try-lock with the (target, service) shape.
    assert "pg_try_advisory_xact_lock" in cur.queries[0][0]
    assert cur.queries[0][1] == (2, 5)
    # Second call inspects prior acceptances scoped to (target, service).
    assert "SELECT 1" in cur.queries[1][0]
    assert "target_team_id" in cur.queries[1][0]
    assert "service_id" in cur.queries[1][0]
    assert cur.queries[1][1] == (2, 5)


def test_resolve_firstblood_false_when_prior_acceptance_exists():
    cur = FakeCursor(
        responses=[
            {"got": True},
            {"?column?": 1},  # SELECT 1 found a prior acceptance
        ]
    )
    assert _resolve_firstblood(cur, 2, 5) is False


def test_resolve_firstblood_false_when_lock_contended():
    """Concurrent submitter holds the slot — we MUST NOT claim firstblood,
    and MUST NOT even issue the SELECT (would race the lock holder)."""
    cur = FakeCursor(responses=[{"got": False}])
    assert _resolve_firstblood(cur, 2, 5) is False
    # Only the try-lock query was issued; no SELECT 1.
    assert len(cur.queries) == 1
    assert "pg_try_advisory_xact_lock" in cur.queries[0][0]


def test_resolve_firstblood_handles_null_lock_row_as_contended():
    """If the DB driver returns no row for the lock query (defensive), we
    should treat it as 'lock not acquired' rather than crashing."""
    cur = FakeCursor(responses=[None])
    assert _resolve_firstblood(cur, 2, 5) is False
    assert len(cur.queries) == 1


def test_resolve_firstblood_lock_args_are_int():
    """Lock keys must be Python ints — psycopg2 binds str/int differently
    and Postgres needs int4 for the two-arg advisory lock form."""
    cur = FakeCursor(responses=[{"got": True}, None])
    _resolve_firstblood(cur, target_team_id="3", service_id="9")  # type: ignore[arg-type]
    _, params = cur.queries[0]
    assert params == (3, 9)
    assert all(isinstance(p, int) for p in params)
