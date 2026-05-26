from __future__ import annotations

import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel

from .access import require_internal
from .db import get_cursor
from .game_timer import CTFState, load_timer, rotation_seconds, wait_for_next_round


router = APIRouter(tags=["game"])


class GameScheduleRequest(BaseModel):
    start_at: Optional[int] = None
    stop_after_tick: Optional[int] = None
    scoreboard_freeze_tick: Optional[int] = None


def _timer_snapshot() -> Dict[str, Any]:
    with get_cursor(commit=True) as (_conn, cur):
        timer = load_timer(cur)
        timer.sync_scheduled_start(cur)
        timer.load(cur)
        return timer.to_api_dict()


@router.get("/api/v1/game")
def game_status() -> Dict[str, Any]:
    return _timer_snapshot()


@router.post("/api/v1/game/start")
def game_start(
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    require_internal(request, authorization)
    with get_cursor(commit=True) as (_conn, cur):
        timer = load_timer(cur)
        timer.set_desired(cur, CTFState.RUNNING)
        timer.sync_scheduled_start(cur)
        timer.load(cur)
        return timer.to_api_dict()


@router.post("/api/v1/game/pause")
def game_pause(
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    require_internal(request, authorization)
    with get_cursor(commit=True) as (_conn, cur):
        timer = load_timer(cur)
        timer.set_desired(cur, CTFState.SUSPENDED)
        timer.load(cur)
        return timer.to_api_dict()


@router.post("/api/v1/game/stop")
def game_stop(
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    require_internal(request, authorization)
    with get_cursor(commit=True) as (_conn, cur):
        timer = load_timer(cur)
        timer.set_desired(cur, CTFState.STOPPED)
        timer.load(cur)
        return timer.to_api_dict()


@router.post("/api/v1/game/schedule")
def game_schedule(
    body: GameScheduleRequest,
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    require_internal(request, authorization)
    with get_cursor(commit=True) as (_conn, cur):
        timer = load_timer(cur)
        timer.schedule(
            cur,
            start_at=body.start_at,
            stop_after_tick=body.stop_after_tick,
            scoreboard_freeze_tick=body.scoreboard_freeze_tick,
        )
        timer.load(cur)
        return timer.to_api_dict()


@router.get("/api/v1/current_round")
def current_round() -> Dict[str, Any]:
    with get_cursor(commit=True) as (_conn, cur):
        timer = load_timer(cur)
        timer.sync_scheduled_start(cur)
        timer.load(cur)
    now_ts = time.time()
    next_tick_at = timer.tick_end or int(now_ts + rotation_seconds())
    payload = timer.current_round_payload()
    payload["game_state"] = timer.state.value
    payload["seconds_to_next_tick"] = max(0, int(next_tick_at - now_ts)) if timer.tick_end else 0
    return payload


@router.get("/api/v1/next_round")
def next_round(timeout: float = Query(default=130.0, ge=1.0, le=300.0)) -> Dict[str, Any]:
    return wait_for_next_round(timeout)
