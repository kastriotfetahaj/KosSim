from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .attack_compat import build_attack_json, build_teams_json
from .db import get_cursor
from .flag_submit import submit_flags as process_flag_submissions


class FlagSubmitRequest(BaseModel):
    team_token: str = Field(min_length=3)
    flags: List[str] = Field(min_length=1, max_length=256)


def _http_flag_submit_enabled() -> bool:
    return os.getenv("HTTP_FLAG_SUBMIT_ENABLED", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def build_team_router(
    *,
    points: Callable[[Any], float],
    effective_freeze_tick: Callable[[], Optional[int]],
    request_is_internal: Callable[[Request, Optional[str]], bool],
    require_internal: Callable[[Request, Optional[str]], None],
) -> APIRouter:
    router = APIRouter(tags=["teams"])

    @router.get("/api/v1/team/{team_id}/history")
    def team_tick_history(
        team_id: int,
        request: Request,
        limit: int = 60,
        authorization: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        """Per-tick score history for a single team."""
        limit = max(1, min(int(limit), 500))
        freeze_tick = None if request_is_internal(request, authorization) else effective_freeze_tick()
        recent_where = ["team_id = %s"]
        recent_args: List[Any] = [team_id]
        all_where = ["ttp.team_id = %s"]
        all_args: List[Any] = [team_id]
        if freeze_tick is not None:
            recent_where.append("tick <= %s")
            recent_args.append(freeze_tick)
            all_where.append("ttp.tick <= %s")
            all_args.append(freeze_tick)
        with get_cursor(commit=False) as (_conn, cur):
            cur.execute(
                "SELECT id, name, country_code, nat_alias, is_nop FROM teams WHERE id = %s;",
                (team_id,),
            )
            team = cur.fetchone()
            if team is None:
                raise HTTPException(status_code=404, detail="Team not found")

            cur.execute("SELECT id, name FROM services ORDER BY id;")
            services = [{"id": int(r["id"]), "name": r["name"]} for r in cur.fetchall()]

            query_args = recent_args + [limit] + all_args
            cur.execute(
                f"""
                WITH recent_ticks AS (
                    SELECT DISTINCT tick FROM team_tick_points
                    WHERE {' AND '.join(recent_where)}
                    ORDER BY tick DESC
                    LIMIT %s
                ),
                window_bounds AS (
                    SELECT MIN(tick) - 1 AS min_tick FROM recent_ticks
                )
                SELECT ttp.tick, ttp.service_id,
                       ttp.off_points, ttp.def_points,
                       ttp.sla_points, ttp.sla_delta,
                       ttp.flag_captured_count
                FROM team_tick_points ttp, window_bounds wb
                WHERE {' AND '.join(all_where)}
                  AND ttp.tick >= COALESCE(wb.min_tick, 0)
                ORDER BY ttp.tick ASC, ttp.service_id ASC;
                """,
                query_args,
            )
            rows = cur.fetchall()

        prev_per_service: Dict[int, Dict[str, float]] = {}
        by_tick: Dict[int, Dict[str, Any]] = {}
        ticks_seen: List[int] = []

        for r in rows:
            tick = int(r["tick"])
            sid = int(r["service_id"])
            cum_off = float(r["off_points"] or 0)
            cum_def = float(r["def_points"] or 0)
            cum_sla = float(r["sla_points"] or 0)
            sla_delta = float(r["sla_delta"] or 0)
            cum_cap = int(r["flag_captured_count"] or 0)
            prev = prev_per_service.get(sid, {})
            d_off = cum_off - prev.get("off", 0.0)
            d_def = cum_def - prev.get("def", 0.0)
            prev_service_score = (
                prev.get("off", 0.0) + prev.get("def", 0.0)
            ) * prev.get("sla", 0.0)
            service_score = (cum_off + cum_def) * cum_sla
            d_cap = cum_cap - int(prev.get("cap", 0))
            prev_per_service[sid] = {
                "off": cum_off,
                "def": cum_def,
                "sla": cum_sla,
                "cap": cum_cap,
            }
            if tick not in by_tick:
                by_tick[tick] = {"tick": tick, "services": {}, "totals": {}}
                ticks_seen.append(tick)
            by_tick[tick]["services"][str(sid)] = {
                "attack_points": points(cum_off),
                "attack_delta": points(d_off),
                "defense_points": points(cum_def),
                "defense_delta": points(d_def),
                "uptime_points": points(cum_sla),
                "uptime_delta": points(sla_delta),
                "service_score": points(service_score),
                "service_delta": points(service_score - prev_service_score),
                "flags_captured": cum_cap,
                "flags_captured_delta": d_cap,
            }

        for tick in ticks_seen:
            agg = {
                "attack_points": 0.0,
                "attack_delta": 0.0,
                "defense_points": 0.0,
                "defense_delta": 0.0,
                "uptime_points": 0.0,
                "uptime_delta": 0.0,
                "service_score": 0.0,
                "service_delta": 0.0,
                "flags_captured": 0,
                "flags_captured_delta": 0,
            }
            for sb in by_tick[tick]["services"].values():
                for k in agg.keys():
                    agg[k] += sb[k]
            agg["score"] = points(agg["service_score"])
            agg["score_delta"] = points(agg["service_delta"])
            for k in (
                "attack_points",
                "attack_delta",
                "defense_points",
                "defense_delta",
                "uptime_points",
                "uptime_delta",
                "service_score",
                "service_delta",
            ):
                agg[k] = points(agg[k])
            by_tick[tick]["totals"] = agg

        ticks_desc = sorted(ticks_seen, reverse=True)[:limit]
        ticks_out = [by_tick[t] for t in ticks_desc]

        return {
            "team": {
                "id": int(team["id"]),
                "name": team["name"],
                "country_code": (team["country_code"] or "XK").upper(),
                "nat_alias": team["nat_alias"],
                "is_nop": bool(team["is_nop"]),
            },
            "services": services,
            "ticks": ticks_out,
        }

    @router.get("/api/v1/attack_info")
    def attack_info(
        request: Request,
        team: Optional[str] = None,
        service: Optional[str] = None,
        authorization: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        args: List[Any] = []
        where: List[str] = []
        if team:
            where.append("t.name = %s")
            args.append(team)
        if service:
            where.append("s.name = %s")
            args.append(service)
        freeze_tick = None if request_is_internal(request, authorization) else effective_freeze_tick()
        if freeze_tick is not None:
            where.append("fr.tick <= %s")
            args.append(freeze_tick)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        sql = f"""
            SELECT t.name AS team_name, s.name AS service_name,
                   f.payload, f.attack_info,
                   fr.tick AS tick
            FROM flags f
            JOIN teams t ON t.id = f.team_id
            JOIN services s ON s.id = f.service_id
            JOIN flag_rounds fr ON fr.round_id = f.round_id
            {where_sql}
            ORDER BY fr.tick DESC, t.name ASC, s.name ASC, f.payload ASC;
        """
        out: Dict[int, Dict[str, Dict[str, Dict[int, Any]]]] = {}
        with get_cursor(commit=False) as (_conn, cur):
            cur.execute(sql, args)
            for row in cur.fetchall():
                t = row["team_name"]
                s = row["service_name"]
                tick = int(row["tick"]) if row["tick"] is not None else 0
                payload = int(row["payload"] or 0)
                tick_bucket = out.setdefault(tick, {})
                team_bucket = tick_bucket.setdefault(t, {})
                svc_bucket = team_bucket.setdefault(s, {})
                svc_bucket[payload] = row["attack_info"]
        return out

    @router.get("/api/teams.json")
    def teams_json() -> Dict[str, Any]:
        return build_teams_json()

    @router.get("/api/team/{team_name}")
    def team_detail(
        team_name: str,
        request: Request,
        authorization: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        require_internal(request, authorization)
        with get_cursor(commit=False) as (_conn, cur):
            cur.execute(
                """
                SELECT t.id, t.name, t.country_code, t.nat_alias, t.is_nop,
                       sc.attack_points, sc.defense_points, sc.uptime_points,
                       sc.hacked_penalty_points, sc.challenge_points, sc.sla_points,
                       sc.total, sc.updated_at
                FROM teams t
                JOIN scores sc ON sc.team_id = t.id
                WHERE t.name = %s;
                """,
                (team_name,),
            )
            team = cur.fetchone()
            if team is None:
                raise HTTPException(status_code=404, detail="Team not found")
            team_id = int(team["id"])

            cur.execute(
                """
                SELECT s.id, s.name, ttp.off_points, ttp.def_points, ttp.sla_points,
                       ttp.sla_delta, ttp.flag_captured_count, ttp.flag_stolen_count,
                       ttp.tick
                FROM services s
                LEFT JOIN LATERAL (
                    SELECT tick, off_points, def_points, sla_points, sla_delta,
                           flag_captured_count, flag_stolen_count
                    FROM team_tick_points
                    WHERE team_id = %s AND service_id = s.id
                    ORDER BY tick DESC LIMIT 1
                ) ttp ON TRUE
                ORDER BY s.id;
                """,
                (team_id,),
            )
            services_rows = cur.fetchall()

            cur.execute(
                """
                SELECT sh.tick, sh.status, sh.flag_avail, s.name AS service_name,
                       sh.checked_at, sh.runtime_seconds, sh.attack_info
                FROM service_health sh
                JOIN services s ON s.id = sh.service_id
                WHERE sh.team_id = %s
                  AND sh.tick IS NOT NULL
                ORDER BY sh.tick DESC, s.id ASC
                LIMIT 60;
                """,
                (team_id,),
            )
            recent_health = cur.fetchall()

            cur.execute(
                """
                SELECT sub.id, sub.submitted_at, sub.result, sub.is_firstblood,
                       sub.tick_issued, sub.payload, sub.points_awarded,
                       sub.flag, victim.name AS target_team, svc.name AS service_name
                FROM submissions sub
                LEFT JOIN teams victim ON victim.id = sub.target_team_id
                LEFT JOIN services svc ON svc.id = sub.service_id
                WHERE sub.submitter_team_id = %s
                ORDER BY sub.submitted_at DESC
                LIMIT 50;
                """,
                (team_id,),
            )
            submitted = cur.fetchall()

            cur.execute(
                """
                SELECT sub.id, sub.submitted_at, sub.tick_issued, sub.payload,
                       sub.is_firstblood, attacker.name AS attacker, svc.name AS service_name
                FROM submissions sub
                JOIN teams attacker ON attacker.id = sub.submitter_team_id
                LEFT JOIN services svc ON svc.id = sub.service_id
                WHERE sub.target_team_id = %s
                  AND sub.result = 'accepted'
                ORDER BY sub.submitted_at DESC
                LIMIT 50;
                """,
                (team_id,),
            )
            captured_from = cur.fetchall()

        return {
            "team": {
                "id": team_id,
                "name": team["name"],
                "country_code": team["country_code"],
                "nat_alias": team["nat_alias"],
                "is_nop": bool(team["is_nop"]),
                "attack_points": points(team["attack_points"]),
                "defense_points": points(team["defense_points"]),
                "uptime_points": points(team["uptime_points"]),
                "hacked_penalty_points": points(team["hacked_penalty_points"]),
                "challenge_points": points(team["challenge_points"]),
                "sla_points": points(team["sla_points"]),
                "total": points(team["total"]),
                "updated_at": team["updated_at"].isoformat() + "Z" if team["updated_at"] else None,
            },
            "services": [
                {
                    "service_id": int(r["id"]),
                    "service_name": r["name"],
                    "off_points": points(r["off_points"] or 0),
                    "def_points": points(r["def_points"] or 0),
                    "sla_points": points(r["sla_points"] or 0),
                    "sla_delta": points(r["sla_delta"] or 0),
                    "flag_captured_count": int(r["flag_captured_count"] or 0),
                    "flag_stolen_count": int(r["flag_stolen_count"] or 0),
                    "latest_tick": int(r["tick"]) if r["tick"] is not None else None,
                }
                for r in services_rows
            ],
            "checker_history": [
                {
                    "tick": int(r["tick"]),
                    "service": r["service_name"],
                    "status": r["status"],
                    "flag_avail": r["flag_avail"],
                    "attack_info": r["attack_info"],
                    "checked_at": r["checked_at"].isoformat() + "Z" if r["checked_at"] else None,
                    "runtime_seconds": float(r["runtime_seconds"]) if r["runtime_seconds"] is not None else None,
                }
                for r in recent_health
            ],
            "recent_submissions": [
                {
                    "id": int(r["id"]),
                    "timestamp": r["submitted_at"].timestamp() if r["submitted_at"] else None,
                    "result": r["result"],
                    "is_firstblood": bool(r["is_firstblood"]),
                    "tick_issued": r["tick_issued"],
                    "payload": r["payload"],
                    "points_awarded": int(r["points_awarded"] or 0),
                    "target_team": r["target_team"],
                    "service": r["service_name"],
                    "flag": r["flag"],
                }
                for r in submitted
            ],
            "recent_captures_from": [
                {
                    "id": int(r["id"]),
                    "timestamp": r["submitted_at"].timestamp() if r["submitted_at"] else None,
                    "attacker": r["attacker"],
                    "service": r["service_name"],
                    "tick_issued": r["tick_issued"],
                    "payload": r["payload"],
                    "is_firstblood": bool(r["is_firstblood"]),
                }
                for r in captured_from
            ],
        }

    @router.get("/api/attack.json")
    def attack_json() -> Dict[str, Any]:
        return build_attack_json()

    @router.post("/api/v1/flags/submit")
    def submit_flags_http(payload: FlagSubmitRequest, request: Request) -> Dict[str, Any]:
        if not _http_flag_submit_enabled():
            raise HTTPException(status_code=404, detail="Flag submission is TCP-only")
        source_ip = request.headers.get("x-source-ip") or (
            request.client.host if request.client else "unknown"
        )
        with get_cursor(commit=False) as (_conn, cur):
            cur.execute(
                "SELECT id FROM teams WHERE submit_token = %s;",
                (payload.team_token,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=401, detail="Invalid team token")
            cur.execute("SELECT is_nop FROM teams WHERE id = %s;", (row["id"],))
            if cur.fetchone()["is_nop"]:
                raise HTTPException(status_code=403, detail="NOP team cannot submit flags")
            submitter_id = int(row["id"])

        result = process_flag_submissions(
            submitter_team_id=submitter_id,
            flags=payload.flags,
            source_ip=source_ip,
            require_running=True,
        )
        if result.get("offline"):
            raise HTTPException(status_code=503, detail="CTF is not running")
        clean = {k: v for k, v in result.items() if k != "offline"}
        for row in clean.get("results", []):
            row.pop("tcp_line", None)
        return clean

    return router
