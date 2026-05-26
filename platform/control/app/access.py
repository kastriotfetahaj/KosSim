from __future__ import annotations

import os
from typing import Optional

from fastapi import HTTPException, Request

from .admin_auth import is_authenticated
from .db import get_cursor
from .game_timer import load_timer


def admin_token_ok(authorization: Optional[str]) -> bool:
    required = os.getenv("GAME_ADMIN_TOKEN", "").strip()
    if not required:
        return False
    if not authorization:
        return False
    if authorization.startswith("Bearer "):
        return authorization[7:] == required
    return authorization == required


def request_is_internal(request: Request, authorization: Optional[str]) -> bool:
    return is_authenticated(request) or admin_token_ok(authorization)


def require_internal(request: Request, authorization: Optional[str]) -> None:
    if not request_is_internal(request, authorization):
        raise HTTPException(status_code=401, detail="Admin authentication required")


def effective_freeze_tick() -> Optional[int]:
    with get_cursor(commit=False) as (_conn, cur):
        timer = load_timer(cur)
        freeze = timer.scoreboard_freeze_tick
        if freeze is None or freeze < 1:
            return None
        if timer.current_tick >= freeze:
            return freeze
    return None
