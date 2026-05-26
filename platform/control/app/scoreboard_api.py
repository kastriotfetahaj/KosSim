from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request

from .db import get_cursor


def build_scoreboard_router(
    *,
    scoreboard_timing: Callable[[], Dict[str, Any]],
    build_scoreboard_data: Callable[..., Dict[str, Any]],
    max_accepted_per_round: Callable[[], int],
    request_is_internal: Callable[[Request, Optional[str]], bool],
) -> APIRouter:
    router = APIRouter(tags=["scoreboard"])

    @router.get("/api/v1/scoreboard")
    def scoreboard(
        request: Request,
        include_nop: bool = False,
        public: bool = False,
        authorization: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        internal = request_is_internal(request, authorization)
        if include_nop and not internal:
            raise HTTPException(status_code=401, detail="Admin authentication required")
        timing = scoreboard_timing()
        data = build_scoreboard_data(include_nop=include_nop and internal, frozen=public or not internal)
        timer = timing["timer"]
        return {
            "generated_at": dt.datetime.utcnow().isoformat() + "Z",
            "rotation_seconds": timing["rotation"],
            "round_id": timing["current_round_number"],
            "game_state": timer.state.value,
            "desired_state": timer.desired_state.value,
            "start_at": timer.start_at,
            "stop_after_tick": timer.stop_after_tick,
            "next_tick_at_epoch": timing["next_tick_at"],
            "seconds_to_next_tick": timing["seconds_to_next_tick"],
            "frozen": data.get("frozen", False),
            "freeze_tick": data.get("freeze_tick"),
            "max_accepted_per_team_per_round": max_accepted_per_round(),
            "display_tick": data.get("display_tick"),
            "services": data["services"],
            "rows": data["rows"],
            "service_tops": data["service_tops"],
            "tick_activity": data.get("tick_activity"),
        }

    @router.get("/api/v1/firstbloods")
    def firstbloods(since: Optional[float] = None, limit: int = 50) -> Dict[str, Any]:
        """Recent first-blood events for the scoreboard toast feed."""
        limit = max(1, min(int(limit), 200))
        args: List[Any] = []
        where = ["sub.is_firstblood = TRUE"]
        if since is not None and since > 0:
            where.append("sub.submitted_at > to_timestamp(%s)")
            args.append(float(since))
        sql = f"""
            SELECT
                sub.id,
                sub.submitted_at,
                sub.tick_issued,
                sub.payload,
                attacker.name AS submitter_team,
                attacker.country_code AS submitter_country,
                victim.name AS target_team,
                victim.country_code AS target_country,
                svc.name AS service_slug,
                COALESCE(NULLIF(svc.display_name, ''), svc.name) AS service_name,
                COALESCE(NULLIF(svc.display_name, ''), svc.name) AS service_display_name
            FROM submissions sub
            JOIN teams attacker ON attacker.id = sub.submitter_team_id
            LEFT JOIN teams victim ON victim.id = sub.target_team_id
            LEFT JOIN services svc ON svc.id = sub.service_id
            WHERE {' AND '.join(where)}
            ORDER BY sub.submitted_at DESC
            LIMIT %s;
        """
        args.append(limit)
        with get_cursor(commit=False) as (_conn, cur):
            cur.execute(sql, args)
            rows = cur.fetchall()
        events = [
            {
                "id": int(r["id"]),
                "timestamp": r["submitted_at"].timestamp() if r["submitted_at"] else None,
                "submitter_team": r["submitter_team"],
                "submitter_country": r["submitter_country"],
                "target_team": r["target_team"],
                "target_country": r["target_country"],
                "service": r["service_name"],
                "service_slug": r["service_slug"],
                "service_display_name": r["service_display_name"],
                "tick_issued": r["tick_issued"],
                "payload": r["payload"],
            }
            for r in rows
        ]
        return {
            "generated_at": dt.datetime.utcnow().isoformat() + "Z",
            "count": len(events),
            "events": events,
        }

    return router
