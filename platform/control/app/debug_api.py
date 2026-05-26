from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request

from .access import effective_freeze_tick, request_is_internal, require_internal
from .db import get_cursor


def build_debug_router(
    status_grid_data: Callable[[Optional[int]], Dict[str, Any]],
) -> APIRouter:
    router = APIRouter(tags=["debug"])

    @router.get("/api/v1/topology")
    def topology(
        request: Request,
        authorization: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        require_internal(request, authorization)
        with get_cursor(commit=False) as (_conn, cur):
            cur.execute(
                """
                SELECT
                    t.name AS team_name,
                    t.is_nop,
                    t.nat_alias,
                    s.name AS service_name,
                    ts.host,
                    ts.port,
                    ts.enabled
                FROM team_services ts
                JOIN teams t ON t.id = ts.team_id
                JOIN services s ON s.id = ts.service_id
                ORDER BY t.name ASC, s.name ASC;
                """
            )
            rows = [dict(row) for row in cur.fetchall()]
        return {"rows": rows}

    @router.get("/api/v1/flags/current/{team_name}/{service_name}")
    def current_flag(
        team_name: str,
        service_name: str,
        request: Request,
        authorization: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        require_internal(request, authorization)
        with get_cursor(commit=False) as (_conn, cur):
            cur.execute(
                """
                SELECT
                    f.flag,
                    f.round_id,
                    f.created_at,
                    f.expires_at,
                    t.name AS team_name,
                    s.name AS service_name
                FROM flags f
                JOIN teams t ON t.id = f.team_id
                JOIN services s ON s.id = f.service_id
                WHERE t.name = %s AND s.name = %s AND f.active = TRUE
                ORDER BY f.created_at DESC
                LIMIT 1;
                """,
                (team_name, service_name),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="No active flag found for team/service")
            return dict(row)

    @router.get("/api/v1/status")
    def status_grid_json(
        request: Request,
        authorization: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        tick = None if request_is_internal(request, authorization) else effective_freeze_tick()
        return status_grid_data(tick)

    return router
