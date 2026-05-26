"""Postgres-backed CTF game timer (ECSC CTFTimer subset)."""

from __future__ import annotations

import datetime as dt
import os
import time
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from .db import get_cursor


class CTFState(str, Enum):
    STOPPED = "STOPPED"
    SUSPENDED = "SUSPENDED"
    RUNNING = "RUNNING"


def rotation_seconds() -> int:
    return int(os.getenv("ROTATION_SECONDS", "120"))


def _auto_start() -> bool:
    return os.getenv("GAME_AUTO_START", "1") not in ("0", "false", "False", "")


def scoreboard_freeze_tick_from_env() -> Optional[int]:
    raw = os.getenv("SCOREBOARD_FREEZE_TICK", "0").strip()
    if not raw or raw == "0":
        return None
    return int(raw)


class GameTimer:
    def __init__(self) -> None:
        self.state: CTFState = CTFState.STOPPED
        self.desired_state: CTFState = CTFState.STOPPED
        self.current_tick: int = 0
        self.tick_start: Optional[int] = None
        self.tick_end: Optional[int] = None
        self.start_at: Optional[int] = None
        self.stop_after_tick: Optional[int] = None
        self.scoreboard_freeze_tick: Optional[int] = scoreboard_freeze_tick_from_env()

    def load(self, cur: Any) -> None:
        cur.execute(
            """
            SELECT state, desired_state, current_tick, tick_start, tick_end,
                   start_at, stop_after_tick, scoreboard_freeze_tick
            FROM game_state WHERE id = 1;
            """
        )
        row = cur.fetchone()
        if row is None:
            return
        self.state = CTFState(row["state"])
        self.desired_state = CTFState(row["desired_state"])
        self.current_tick = int(row["current_tick"] or 0)
        self.tick_start = int(row["tick_start"]) if row["tick_start"] is not None else None
        self.tick_end = int(row["tick_end"]) if row["tick_end"] is not None else None
        self.start_at = int(row["start_at"]) if row["start_at"] is not None else None
        self.stop_after_tick = (
            int(row["stop_after_tick"]) if row["stop_after_tick"] is not None else None
        )
        if row["scoreboard_freeze_tick"] is not None:
            self.scoreboard_freeze_tick = int(row["scoreboard_freeze_tick"])

    def _persist(self, cur: Any) -> None:
        cur.execute(
            """
            UPDATE game_state SET
                state = %s,
                desired_state = %s,
                current_tick = %s,
                tick_start = %s,
                tick_end = %s,
                start_at = %s,
                stop_after_tick = %s,
                scoreboard_freeze_tick = %s,
                updated_at = NOW()
            WHERE id = 1;
            """,
            (
                self.state.value,
                self.desired_state.value,
                self.current_tick,
                self.tick_start,
                self.tick_end,
                self.start_at,
                self.stop_after_tick,
                self.scoreboard_freeze_tick,
            ),
        )

    def ensure_row(self, cur: Any) -> None:
        desired = CTFState.RUNNING if _auto_start() else CTFState.STOPPED
        freeze = scoreboard_freeze_tick_from_env()
        cur.execute(
            """
            INSERT INTO game_state (
                id, state, desired_state, current_tick, scoreboard_freeze_tick
            )
            VALUES (1, %s, %s, 0, %s)
            ON CONFLICT (id) DO NOTHING;
            """,
            (desired.value, desired.value, freeze),
        )
        self.load(cur)

    def sync_scheduled_start(self, cur: Any) -> None:
        """Honor start_at / desired_state and open tick 1 when the game should run."""
        self.ensure_row(cur)
        now = int(time.time())
        if self.desired_state != CTFState.RUNNING:
            return
        if self.start_at is not None and now < self.start_at:
            return
        if self.state != CTFState.RUNNING:
            self.state = CTFState.RUNNING
        if self.current_tick < 1:
            self._open_tick(cur, now, tick=1)
        else:
            self._persist(cur)

    def boundary_ready(self) -> Optional[Tuple[int, dt.datetime, dt.datetime]]:
        """If the current tick has ended, return (tick, starts_at, ends_at) to process."""
        if self.state != CTFState.RUNNING:
            return None
        if self.current_tick < 1 or self.tick_start is None or self.tick_end is None:
            return None
        now = int(time.time())
        if now < self.tick_end:
            return None
        return (
            self.current_tick,
            dt.datetime.utcfromtimestamp(self.tick_start),
            dt.datetime.utcfromtimestamp(self.tick_end),
        )

    def finish_boundary(self, cur: Any) -> None:
        """Call after rotator processed a tick boundary."""
        self.ensure_row(cur)
        now = int(time.time())
        closed = self.current_tick

        if self.desired_state != CTFState.RUNNING:
            self.state = self.desired_state
            self.current_tick = 0 if self.state == CTFState.STOPPED else closed
            self.tick_start = None
            self.tick_end = None
            self._persist(cur)
            return

        if self.stop_after_tick is not None and closed >= self.stop_after_tick:
            self.state = CTFState.STOPPED
            self.desired_state = CTFState.STOPPED
            self.tick_start = None
            self.tick_end = None
            self._persist(cur)
            return

        self._open_tick(cur, now, tick=closed + 1)

    def _open_tick(self, cur: Any, now: int, tick: int) -> None:
        rot = rotation_seconds()
        self.current_tick = tick
        self.tick_start = now
        self.tick_end = now + rot
        self.state = CTFState.RUNNING
        self._persist(cur)

    def set_desired(self, cur: Any, desired: CTFState) -> None:
        self.ensure_row(cur)
        self.desired_state = desired
        if desired == CTFState.STOPPED:
            self.state = CTFState.STOPPED
            self.current_tick = 0
            self.tick_start = None
            self.tick_end = None
        elif desired == CTFState.SUSPENDED:
            if self.state == CTFState.RUNNING:
                # Suspend after the in-flight tick completes (finish_boundary).
                pass
            else:
                self.state = CTFState.SUSPENDED
        elif desired == CTFState.RUNNING:
            if self.state == CTFState.STOPPED and self.current_tick < 1:
                self.state = CTFState.RUNNING
        self._persist(cur)

    def schedule(
        self,
        cur: Any,
        *,
        start_at: Optional[int] = None,
        stop_after_tick: Optional[int] = None,
        scoreboard_freeze_tick: Optional[int] = None,
    ) -> None:
        self.ensure_row(cur)
        if start_at is not None:
            self.start_at = start_at
        if stop_after_tick is not None:
            self.stop_after_tick = stop_after_tick
        if scoreboard_freeze_tick is not None:
            self.scoreboard_freeze_tick = scoreboard_freeze_tick
        self._persist(cur)

    def to_api_dict(self) -> Dict[str, Any]:
        now = int(time.time())
        seconds_to_next = 0
        if self.tick_end is not None and now < self.tick_end:
            seconds_to_next = self.tick_end - now
        return {
            "state": self.state.value,
            "desired_state": self.desired_state.value,
            "current_tick": self.current_tick,
            "tick_start": self.tick_start,
            "tick_end": self.tick_end,
            "start_at": self.start_at,
            "stop_after_tick": self.stop_after_tick,
            "scoreboard_freeze_tick": self.scoreboard_freeze_tick,
            "rotation_seconds": rotation_seconds(),
            "seconds_to_next_tick": seconds_to_next,
            "is_running": self.state == CTFState.RUNNING,
        }

    def current_round_payload(self) -> Dict[str, Any]:
        if self.current_tick < 1 or self.tick_start is None:
            return {"round": 0, "time": None}
        start = dt.datetime.utcfromtimestamp(self.tick_start).strftime("%Y-%m-%dT%H:%M:%S")
        return {"round": self.current_tick, "time": start}


def load_timer(cur: Any) -> GameTimer:
    timer = GameTimer()
    timer.ensure_row(cur)
    return timer


def wait_for_next_round(timeout: float) -> Dict[str, Any]:
    deadline = time.time() + timeout
    with get_cursor(commit=False) as (_conn, cur):
        timer = load_timer(cur)
        target_end = timer.tick_end
    if target_end is None:
        time.sleep(min(timeout, 1.0))
        with get_cursor(commit=False) as (_conn, cur):
            return load_timer(cur).current_round_payload()
    while time.time() < deadline:
        if int(time.time()) >= target_end:
            break
        time.sleep(0.25)
    with get_cursor(commit=True) as (_conn, cur):
        timer = load_timer(cur)
        timer.sync_scheduled_start(cur)
        if timer.boundary_ready():
            # Let rotator advance; API still returns the new tick after sleep.
            pass
        timer.load(cur)
        return timer.current_round_payload()
