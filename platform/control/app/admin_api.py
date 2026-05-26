"""JSON admin API consumed by the React SPA.

Sits alongside the legacy HTML admin in admin_panel.py. Same session cookie
auth, but every endpoint returns JSON and uses HTTP status codes (401 on
unauth) instead of redirects.
"""

from __future__ import annotations

import json
import os
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .admin_auth import (
    is_authenticated,
    login_user,
    logout_user,
    require_admin,
    verify_credentials,
)
from .admin_panel import (
    _checker_status_chart_data,
    _decode_flag_report,
    _game_summary,
    _submission_chart_data,
)
from .db import get_cursor
from .event_log import LEVEL_LABELS, LogLevel, write_log
from .flag_crypto import flag_regex_pattern
from .game_timer import CTFState, load_timer
from .networking import build_router_bundle, load_network_plans
from .observability import build_observability
from .vulnboxes import (
    VALID_ACTIONS,
    enqueue_vulnbox_action,
    ensure_vulnboxes,
    record_vulnbox_event,
    serialize_vulnbox,
)


router = APIRouter(prefix="/admin/api", tags=["admin-api"])


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class LoginBody(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


@router.post("/login")
def api_login(request: Request, body: LoginBody) -> Dict[str, Any]:
    if not verify_credentials(body.username, body.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    login_user(request)
    write_log("admin", "Operator signed in (api)", level=LogLevel.INFO)
    return {"ok": True, "username": body.username}


@router.post("/logout")
def api_logout(request: Request) -> Dict[str, Any]:
    logout_user(request)
    return {"ok": True}


@router.get("/me")
def api_me(request: Request) -> Dict[str, Any]:
    if not is_authenticated(request):
        return {"authenticated": False}
    return {
        "authenticated": True,
        "username": str(request.session.get("admin_user")),
    }


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@router.get("/dashboard")
def api_dashboard(_: str = Depends(require_admin)) -> Dict[str, Any]:
    return {
        "summary": _game_summary(),
        "submissions_chart": _submission_chart_data(),
        "checkers_chart": _checker_status_chart_data(),
    }


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


_CHART_COLORS = [
    "#6ea8ff",
    "#4ade80",
    "#fbbf24",
    "#f87171",
    "#a78bfa",
    "#38bdf8",
    "#fb923c",
    "#f472b6",
    "#2dd4bf",
    "#c084fc",
]


def _ticks_window(cur: Any, limit: int) -> tuple[int, int, List[int]]:
    cur.execute(
        """
        SELECT MAX(fr.tick) AS latest_tick
        FROM score_snapshots ss
        JOIN flag_rounds fr ON fr.round_id = ss.round_id;
        """
    )
    row = cur.fetchone()
    latest = int(row["latest_tick"] or 0) if row else 0
    if latest <= 0:
        return 0, 0, []
    start = max(1, latest - limit + 1)
    return start, latest, list(range(start, latest + 1))


def _series_color(index: int) -> str:
    return _CHART_COLORS[index % len(_CHART_COLORS)]


@router.get("/analytics")
def api_analytics(
    ticks: int = Query(default=60, ge=2, le=500),
    top: int = Query(default=8, ge=1, le=20),
    _: str = Depends(require_admin),
) -> Dict[str, Any]:
    with get_cursor(commit=False) as (_conn, cur):
        start_tick, latest_tick, tick_values = _ticks_window(cur, ticks)
        labels = [str(t) for t in tick_values]

        if not tick_values:
            return {
                "latest_tick": 0,
                "tick_range": {"start": 0, "end": 0, "labels": []},
                "top_teams": [],
                "score_history": {"labels": [], "datasets": []},
                "service_activity": {"labels": [], "services": []},
                "sla_trends": {"labels": [], "datasets": []},
                "first_bloods": [],
                "heatmap": {"attackers": [], "victims": [], "cells": [], "max": 0},
            }

        cur.execute(
            """
            SELECT t.id, t.name, t.country_code, COALESCE(SUM(ss.service_total), 0) AS total
            FROM teams t
            JOIN score_snapshots ss ON ss.team_id = t.id
            JOIN flag_rounds fr ON fr.round_id = ss.round_id
            WHERE fr.tick = %s
              AND t.is_nop = FALSE
            GROUP BY t.id, t.name, t.country_code
            ORDER BY total DESC, t.name ASC
            LIMIT %s;
            """,
            (latest_tick, top),
        )
        top_teams = [
            {
                "id": int(r["id"]),
                "name": r["name"],
                "country_code": (r["country_code"] or "XK").upper(),
                "total": float(r["total"] or 0),
            }
            for r in cur.fetchall()
        ]
        top_team_ids = [team["id"] for team in top_teams]

        history_by_team: Dict[int, Dict[int, float]] = {tid: {} for tid in top_team_ids}
        if top_team_ids:
            cur.execute(
                """
                SELECT fr.tick, ss.team_id, COALESCE(SUM(ss.service_total), 0) AS total
                FROM score_snapshots ss
                JOIN flag_rounds fr ON fr.round_id = ss.round_id
                WHERE ss.team_id = ANY(%s)
                  AND fr.tick BETWEEN %s AND %s
                GROUP BY fr.tick, ss.team_id
                ORDER BY fr.tick ASC, ss.team_id ASC;
                """,
                (top_team_ids, start_tick, latest_tick),
            )
            for row in cur.fetchall():
                history_by_team[int(row["team_id"])][int(row["tick"])] = float(row["total"] or 0)

        score_datasets = [
            {
                "label": team["name"],
                "data": [round(history_by_team[team["id"]].get(t, 0.0), 4) for t in tick_values],
                "backgroundColor": _series_color(i),
            }
            for i, team in enumerate(top_teams)
        ]

        cur.execute(
            """
            SELECT id, name, COALESCE(NULLIF(display_name, ''), name) AS display_name
            FROM services
            ORDER BY id ASC;
            """
        )
        services = [
            {"id": int(r["id"]), "name": r["name"], "display_name": r["display_name"]}
            for r in cur.fetchall()
        ]

        activity: Dict[int, Dict[int, Dict[str, int]]] = {
            svc["id"]: {tick: {"attackers": 0, "victims": 0, "captures": 0} for tick in tick_values}
            for svc in services
        }
        cur.execute(
            """
            SELECT sub.tick_issued AS tick,
                   sub.service_id,
                   COUNT(*) AS captures,
                   COUNT(DISTINCT sub.submitter_team_id) AS attackers,
                   COUNT(DISTINCT sub.target_team_id) AS victims
            FROM submissions sub
            JOIN teams attacker ON attacker.id = sub.submitter_team_id
            JOIN teams victim ON victim.id = sub.target_team_id
            WHERE sub.result = 'accepted'
              AND sub.tick_issued BETWEEN %s AND %s
              AND attacker.is_nop = FALSE
              AND victim.is_nop = FALSE
            GROUP BY sub.tick_issued, sub.service_id
            ORDER BY sub.tick_issued ASC, sub.service_id ASC;
            """,
            (start_tick, latest_tick),
        )
        for row in cur.fetchall():
            sid = int(row["service_id"])
            tick = int(row["tick"])
            if sid in activity and tick in activity[sid]:
                activity[sid][tick] = {
                    "attackers": int(row["attackers"] or 0),
                    "victims": int(row["victims"] or 0),
                    "captures": int(row["captures"] or 0),
                }
        service_activity = [
            {
                "id": svc["id"],
                "name": svc["display_name"],
                "slug": svc["name"],
                "attackers": [activity[svc["id"]][t]["attackers"] for t in tick_values],
                "victims": [activity[svc["id"]][t]["victims"] for t in tick_values],
                "captures": [activity[svc["id"]][t]["captures"] for t in tick_values],
            }
            for svc in services
        ]

        sla_by_service: Dict[int, Dict[int, float]] = {
            svc["id"]: {tick: 0.0 for tick in tick_values} for svc in services
        }
        cur.execute(
            """
            SELECT sh.tick,
                   sh.service_id,
                   SUM(CASE WHEN sh.is_up THEN 1 ELSE 0 END) AS up_count,
                   COUNT(*) AS total_count
            FROM service_health sh
            JOIN teams t ON t.id = sh.team_id
            WHERE sh.tick BETWEEN %s AND %s
              AND t.is_nop = FALSE
            GROUP BY sh.tick, sh.service_id
            ORDER BY sh.tick ASC, sh.service_id ASC;
            """,
            (start_tick, latest_tick),
        )
        for row in cur.fetchall():
            sid = int(row["service_id"])
            tick = int(row["tick"])
            total_count = int(row["total_count"] or 0)
            pct = 0.0 if total_count <= 0 else (int(row["up_count"] or 0) / total_count) * 100.0
            if sid in sla_by_service and tick in sla_by_service[sid]:
                sla_by_service[sid][tick] = round(pct, 2)
        sla_datasets = [
            {
                "label": svc["display_name"],
                "data": [sla_by_service[svc["id"]][t] for t in tick_values],
                "backgroundColor": _series_color(i),
            }
            for i, svc in enumerate(services)
        ]

        cur.execute(
            """
            SELECT sub.id,
                   sub.submitted_at,
                   sub.tick_issued,
                   sub.payload,
                   attacker.name AS attacker,
                   attacker.country_code AS attacker_country,
                   victim.name AS victim,
                   victim.country_code AS victim_country,
                   COALESCE(NULLIF(svc.display_name, ''), svc.name) AS service_name,
                   svc.name AS service_slug
            FROM submissions sub
            JOIN teams attacker ON attacker.id = sub.submitter_team_id
            LEFT JOIN teams victim ON victim.id = sub.target_team_id
            LEFT JOIN services svc ON svc.id = sub.service_id
            WHERE sub.is_firstblood = TRUE
              AND sub.tick_issued BETWEEN %s AND %s
            ORDER BY sub.submitted_at ASC
            LIMIT 160;
            """,
            (start_tick, latest_tick),
        )
        first_bloods = [
            {
                "id": int(r["id"]),
                "timestamp": r["submitted_at"].isoformat() if r["submitted_at"] else None,
                "tick": r["tick_issued"],
                "payload": r["payload"],
                "attacker": r["attacker"],
                "attacker_country": r["attacker_country"],
                "victim": r["victim"],
                "victim_country": r["victim_country"],
                "service": r["service_name"],
                "service_slug": r["service_slug"],
            }
            for r in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT attacker.id AS attacker_id,
                   attacker.name AS attacker,
                   victim.id AS victim_id,
                   victim.name AS victim,
                   COUNT(*) AS captures
            FROM submissions sub
            JOIN teams attacker ON attacker.id = sub.submitter_team_id
            JOIN teams victim ON victim.id = sub.target_team_id
            WHERE sub.result = 'accepted'
              AND sub.tick_issued BETWEEN %s AND %s
              AND attacker.is_nop = FALSE
              AND victim.is_nop = FALSE
            GROUP BY attacker.id, attacker.name, victim.id, victim.name;
            """,
            (start_tick, latest_tick),
        )
        heat_rows = [dict(r) for r in cur.fetchall()]

    attacker_totals: Dict[int, int] = {}
    victim_totals: Dict[int, int] = {}
    attacker_names: Dict[int, str] = {}
    victim_names: Dict[int, str] = {}
    for row in heat_rows:
        attacker_id = int(row["attacker_id"])
        victim_id = int(row["victim_id"])
        captures = int(row["captures"] or 0)
        attacker_totals[attacker_id] = attacker_totals.get(attacker_id, 0) + captures
        victim_totals[victim_id] = victim_totals.get(victim_id, 0) + captures
        attacker_names[attacker_id] = row["attacker"]
        victim_names[victim_id] = row["victim"]
    attackers = [
        {"id": tid, "name": attacker_names[tid], "total": attacker_totals[tid]}
        for tid in sorted(attacker_totals, key=lambda k: (-attacker_totals[k], attacker_names[k]))[:20]
    ]
    victims = [
        {"id": tid, "name": victim_names[tid], "total": victim_totals[tid]}
        for tid in sorted(victim_totals, key=lambda k: (-victim_totals[k], victim_names[k]))[:20]
    ]
    attacker_keep = {row["id"] for row in attackers}
    victim_keep = {row["id"] for row in victims}
    cells = [
        {
            "attacker_id": int(row["attacker_id"]),
            "victim_id": int(row["victim_id"]),
            "captures": int(row["captures"] or 0),
        }
        for row in heat_rows
        if int(row["attacker_id"]) in attacker_keep and int(row["victim_id"]) in victim_keep
    ]
    heat_max = max([cell["captures"] for cell in cells], default=0)

    return {
        "latest_tick": latest_tick,
        "tick_range": {"start": start_tick, "end": latest_tick, "labels": labels},
        "top_teams": top_teams,
        "score_history": {"labels": labels, "datasets": score_datasets},
        "service_activity": {"labels": labels, "services": service_activity},
        "sla_trends": {"labels": labels, "datasets": sla_datasets},
        "first_bloods": first_bloods,
        "heatmap": {"attackers": attackers, "victims": victims, "cells": cells, "max": heat_max},
    }


# ---------------------------------------------------------------------------
# Challenge catalog
# ---------------------------------------------------------------------------


def _challenge_root() -> Path:
    env_path = os.getenv("CHALLENGE_CATALOG_PATH", "").strip()
    candidates = []
    if env_path:
        candidates.append(Path(env_path))
    here = Path(__file__).resolve()
    candidates.extend(
        [
            here.parents[2] / "challenges",
            Path("/challenges"),
            Path.cwd() / "platform" / "challenges",
            Path.cwd().parent / "challenges",
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _read_text_if_exists(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def _load_challenge_catalog(include_patches: bool, reveal_patches: bool) -> List[Dict[str, Any]]:
    root = _challenge_root()
    challenges: List[Dict[str, Any]] = []
    for meta_path in sorted(root.glob("*/meta/service.json")):
        challenge_dir = meta_path.parents[1]
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            challenges.append(
                {
                    "path": challenge_dir.name,
                    "name": challenge_dir.name,
                    "slot": "",
                    "categories": [],
                    "flagstores": 0,
                    "difficulty": "unknown",
                    "runtime": "unknown",
                    "vulnerabilities": 0,
                    "rabbit_holes": 0,
                    "summary": f"metadata read failed: {exc}",
                    "patch_notes": None,
                }
            )
            continue

        readme = _read_text_if_exists(challenge_dir / "README.md")
        patch_notes = None
        if include_patches and reveal_patches:
            patch_notes = _read_text_if_exists(challenge_dir / "patches" / "README.md") or None
        challenges.append(
            {
                "path": challenge_dir.name,
                "name": str(meta.get("name") or challenge_dir.name),
                "slot": str(meta.get("slot") or ""),
                "categories": list(meta.get("categories") or []),
                "flagstores": int(meta.get("flagstores") or 0),
                "difficulty": str(meta.get("difficulty") or "unknown"),
                "runtime": str(meta.get("runtime") or "unknown"),
                "vulnerabilities": int(meta.get("vulnerabilities") or 0),
                "rabbit_holes": int(meta.get("rabbit_holes") or 0),
                "summary": readme,
                "patch_notes": patch_notes,
            }
        )
    challenges.sort(key=lambda c: (c["slot"], c["name"]))
    return challenges


@router.get("/challenges")
def api_challenges(
    include_patches: bool = False,
    _: str = Depends(require_admin),
) -> Dict[str, Any]:
    with get_cursor(commit=False) as (_conn, cur):
        timer = load_timer(cur)
        timer.load(cur)
    can_reveal = timer.state == CTFState.STOPPED or os.getenv("CHALLENGE_PATCHES_VISIBLE", "") in {
        "1",
        "true",
        "TRUE",
        "yes",
        "YES",
    }
    reveal_patches = include_patches and can_reveal
    return {
        "can_reveal_patches": can_reveal,
        "patches_revealed": reveal_patches,
        "challenges": _load_challenge_catalog(include_patches, reveal_patches),
    }


# ---------------------------------------------------------------------------
# Checkers
# ---------------------------------------------------------------------------


def _opt_int(raw: Optional[str]) -> Optional[int]:
    """Treat empty strings / whitespace as None (browsers submit `?tick=`)."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        return int(s)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"expected integer, got {raw!r}")


@router.get("/checkers")
def api_checkers(
    tick: Optional[str] = None,
    team: Optional[str] = None,
    service: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(default=200, ge=1, le=1000),
    _: str = Depends(require_admin),
) -> Dict[str, Any]:
    tick_int = _opt_int(tick)
    where = ["1=1"]
    args: List[Any] = []
    if tick_int is not None:
        where.append("sh.tick = %s")
        args.append(tick_int)
    if team:
        where.append("t.name = %s")
        args.append(team)
    if service:
        where.append("s.name = %s")
        args.append(service)
    if status:
        where.append("sh.status = %s")
        args.append(status)
    if q:
        where.append("(t.name ILIKE %s OR s.name ILIKE %s OR sh.message ILIKE %s)")
        like = f"%{q}%"
        args.extend([like, like, like])
    args.append(limit)
    with get_cursor(commit=False) as (_conn, cur):
        cur.execute("SELECT DISTINCT tick FROM service_health ORDER BY tick DESC LIMIT 60;")
        ticks = [int(r["tick"]) for r in cur.fetchall() if r["tick"]]
        cur.execute("SELECT name FROM teams ORDER BY name;")
        teams = [r["name"] for r in cur.fetchall()]
        cur.execute("SELECT name FROM services ORDER BY name;")
        services = [r["name"] for r in cur.fetchall()]
        cur.execute(
            f"""
            SELECT sh.tick, t.name AS team, s.name AS service, sh.status, sh.message,
                   sh.runtime_seconds, sh.checked_at,
                   cj.id AS job_id, cj.status AS job_status, cj.attempts
            FROM service_health sh
            JOIN teams t ON t.id = sh.team_id
            JOIN services s ON s.id = sh.service_id
            LEFT JOIN checker_jobs cj
              ON cj.tick = sh.tick AND cj.team_id = sh.team_id AND cj.service_id = sh.service_id
            WHERE {' AND '.join(where)}
            ORDER BY sh.tick DESC, t.name, s.name
            LIMIT %s;
            """,
            args,
        )
        rows = [
            {
                "tick": r["tick"],
                "team": r["team"],
                "service": r["service"],
                "status": r["status"],
                "message": r["message"] or "",
                "runtime_seconds": r["runtime_seconds"],
                "checked_at": r["checked_at"].isoformat() if r["checked_at"] else None,
                "job_id": int(r["job_id"]) if r["job_id"] is not None else None,
                "job_status": r["job_status"],
                "attempts": int(r["attempts"] or 0),
            }
            for r in cur.fetchall()
        ]
    return {
        "filters": {"ticks": ticks, "teams": teams, "services": services},
        "rows": rows,
    }


@router.get("/checkers/{job_id}/logs")
def api_checker_job_logs(job_id: int, _: str = Depends(require_admin)) -> Dict[str, Any]:
    with get_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """
            SELECT csl.method, csl.related_tick, csl.payload, csl.status,
                   csl.message, csl.runtime_seconds, csl.trace, csl.created_at
            FROM checker_step_logs csl
            WHERE csl.job_id = %s
            ORDER BY csl.created_at ASC, csl.id ASC;
            """,
            (job_id,),
        )
        rows = [
            {
                "method": r["method"],
                "related_tick": r["related_tick"],
                "payload": r["payload"],
                "status": r["status"],
                "message": r["message"] or "",
                "runtime_seconds": r["runtime_seconds"],
                "trace": r["trace"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in cur.fetchall()
        ]
    return {"rows": rows}


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------


class DecodeBody(BaseModel):
    flag: str = Field(min_length=1)


@router.post("/flags/decode")
def api_flag_decode(body: DecodeBody, _: str = Depends(require_admin)) -> Dict[str, Any]:
    return _decode_flag_report(body.flag)


@router.get("/flags/recent")
def api_flags_recent(
    limit: int = Query(default=80, ge=1, le=500),
    q: Optional[str] = None,
    _: str = Depends(require_admin),
) -> Dict[str, Any]:
    where = ["1=1"]
    args: List[Any] = []
    if q:
        where.append("(t.name ILIKE %s OR s.name ILIKE %s OR f.flag ILIKE %s)")
        like = f"%{q}%"
        args.extend([like, like, like])
    args.append(limit)
    with get_cursor(commit=False) as (_conn, cur):
        cur.execute(
            f"""
            SELECT f.flag, t.name AS team, s.name AS service, fr.tick, f.payload, f.created_at
            FROM flags f
            JOIN teams t ON t.id = f.team_id
            JOIN services s ON s.id = f.service_id
            JOIN flag_rounds fr ON fr.round_id = f.round_id
            WHERE {' AND '.join(where)}
            ORDER BY f.created_at DESC
            LIMIT %s;
            """,
            args,
        )
        rows = [
            {
                "flag": r["flag"],
                "team": r["team"],
                "service": r["service"],
                "tick": r["tick"],
                "payload": r["payload"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in cur.fetchall()
        ]
    return {"pattern": flag_regex_pattern(), "rows": rows}


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------


@router.get("/submissions")
def api_submissions(
    result: Optional[str] = None,
    team: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(default=150, ge=1, le=500),
    _: str = Depends(require_admin),
) -> Dict[str, Any]:
    where = ["1=1"]
    args: List[Any] = []
    if result:
        where.append("sub.result = %s")
        args.append(result)
    if team:
        where.append("att.name = %s")
        args.append(team)
    if q:
        where.append("(att.name ILIKE %s OR COALESCE(vic.name,'') ILIKE %s OR COALESCE(svc.name,'') ILIKE %s OR sub.flag ILIKE %s)")
        like = f"%{q}%"
        args.extend([like, like, like, like])
    args.append(limit)
    with get_cursor(commit=False) as (_conn, cur):
        cur.execute(
            f"""
            SELECT sub.submitted_at, att.name AS submitter, vic.name AS target,
                   svc.name AS service, sub.result, sub.tick_issued, sub.is_firstblood,
                   sub.points_awarded, LEFT(sub.flag, 48) AS flag_short
            FROM submissions sub
            JOIN teams att ON att.id = sub.submitter_team_id
            LEFT JOIN teams vic ON vic.id = sub.target_team_id
            LEFT JOIN services svc ON svc.id = sub.service_id
            WHERE {' AND '.join(where)}
            ORDER BY sub.submitted_at DESC
            LIMIT %s;
            """,
            args,
        )
        rows = [
            {
                "submitted_at": r["submitted_at"].isoformat() if r["submitted_at"] else None,
                "submitter": r["submitter"],
                "target": r["target"],
                "service": r["service"],
                "result": r["result"],
                "tick_issued": r["tick_issued"],
                "is_firstblood": bool(r["is_firstblood"]),
                "points_awarded": float(r["points_awarded"]) if r["points_awarded"] is not None else 0,
                "flag_short": r["flag_short"],
            }
            for r in cur.fetchall()
        ]
    return {"rows": rows, "chart": _submission_chart_data(12)}


# ---------------------------------------------------------------------------
# Game control
# ---------------------------------------------------------------------------


def _timer_snapshot() -> Dict[str, Any]:
    with get_cursor(commit=False) as (_conn, cur):
        timer = load_timer(cur)
        timer.sync_scheduled_start(cur)
        timer.load(cur)
    return timer.to_api_dict()


@router.get("/game")
def api_game(_: str = Depends(require_admin)) -> Dict[str, Any]:
    return _timer_snapshot()


@router.post("/game/start")
def api_game_start(_: str = Depends(require_admin)) -> Dict[str, Any]:
    with get_cursor(commit=True) as (_conn, cur):
        timer = load_timer(cur)
        timer.set_desired(cur, CTFState.RUNNING)
        timer.sync_scheduled_start(cur)
    write_log("game", "Game start requested", level=LogLevel.IMPORTANT)
    return _timer_snapshot()


@router.post("/game/pause")
def api_game_pause(_: str = Depends(require_admin)) -> Dict[str, Any]:
    with get_cursor(commit=True) as (_conn, cur):
        timer = load_timer(cur)
        timer.set_desired(cur, CTFState.SUSPENDED)
    write_log("game", "Game pause requested", level=LogLevel.IMPORTANT)
    return _timer_snapshot()


@router.post("/game/stop")
def api_game_stop(_: str = Depends(require_admin)) -> Dict[str, Any]:
    with get_cursor(commit=True) as (_conn, cur):
        timer = load_timer(cur)
        timer.set_desired(cur, CTFState.STOPPED)
    write_log("game", "Game stop requested", level=LogLevel.IMPORTANT)
    return _timer_snapshot()


class ScheduleBody(BaseModel):
    start_at: Optional[int] = None
    stop_after_tick: Optional[int] = None
    scoreboard_freeze_tick: Optional[int] = None


@router.post("/game/schedule")
def api_game_schedule(
    body: ScheduleBody = Body(...),
    _: str = Depends(require_admin),
) -> Dict[str, Any]:
    with get_cursor(commit=True) as (_conn, cur):
        timer = load_timer(cur)
        timer.schedule(
            cur,
            start_at=body.start_at,
            stop_after_tick=body.stop_after_tick,
            scoreboard_freeze_tick=body.scoreboard_freeze_tick,
        )
    write_log("game", "Schedule updated (api)", level=LogLevel.INFO)
    return _timer_snapshot()


# ---------------------------------------------------------------------------
# Services (team targets)
# ---------------------------------------------------------------------------


@router.get("/services")
def api_services(
    q: Optional[str] = None,
    only: Optional[str] = Query(default=None, pattern="^(on|off)$"),
    _: str = Depends(require_admin),
) -> Dict[str, Any]:
    where = ["1=1"]
    args: List[Any] = []
    if q:
        where.append("(t.name ILIKE %s OR s.name ILIKE %s OR ts.host ILIKE %s)")
        like = f"%{q}%"
        args.extend([like, like, like])
    if only == "on":
        where.append("ts.enabled = TRUE")
    elif only == "off":
        where.append("ts.enabled = FALSE")
    with get_cursor(commit=False) as (_conn, cur):
        cur.execute(
            f"""
            SELECT ts.id, t.name AS team, s.name AS service, ts.enabled, ts.host, ts.port
            FROM team_services ts
            JOIN teams t ON t.id = ts.team_id
            JOIN services s ON s.id = ts.service_id
            WHERE {' AND '.join(where)}
            ORDER BY t.name, s.name;
            """,
            args,
        )
        rows = [
            {
                "id": int(r["id"]),
                "team": r["team"],
                "service": r["service"],
                "enabled": bool(r["enabled"]),
                "host": r["host"],
                "port": int(r["port"]) if r["port"] is not None else None,
            }
            for r in cur.fetchall()
        ]
    return {"rows": rows}


class ToggleBody(BaseModel):
    ts_id: int
    enabled: bool


@router.post("/services/toggle")
def api_services_toggle(body: ToggleBody, _: str = Depends(require_admin)) -> Dict[str, Any]:
    with get_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """
            UPDATE team_services ts SET enabled = %s
            FROM teams t, services s
            WHERE ts.id = %s AND t.id = ts.team_id AND s.id = ts.service_id
            RETURNING t.name AS team, s.name AS service;
            """,
            (body.enabled, body.ts_id),
        )
        row = cur.fetchone()
    if row:
        state = "enabled" if body.enabled else "disabled"
        write_log(
            "services",
            f"Checker target {state}",
            f"{row['team']} / {row['service']}",
            level=LogLevel.WARNING if not body.enabled else LogLevel.INFO,
        )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------


_TEAM_NAME_RE = r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,62}$"
_COUNTRY_RE = r"^[A-Za-z]{2}$"


def _team_row(cur: Any, team_id: int) -> Optional[Dict[str, Any]]:
    cur.execute(
        """
        SELECT id, name, submit_token, nat_alias, is_nop, country_code, created_at
        FROM teams WHERE id = %s;
        """,
        (team_id,),
    )
    row = cur.fetchone()
    return _serialize_team(row) if row else None


def _serialize_team(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "submit_token": row["submit_token"],
        "nat_alias": row["nat_alias"],
        "is_nop": bool(row["is_nop"]),
        "country_code": (row["country_code"] or "XK").upper(),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


@router.get("/teams")
def api_teams_list(_: str = Depends(require_admin)) -> Dict[str, Any]:
    with get_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """
            SELECT id, name, submit_token, nat_alias, is_nop, country_code, created_at
            FROM teams ORDER BY is_nop ASC, name ASC;
            """,
        )
        rows = [_serialize_team(r) for r in cur.fetchall()]
    return {"rows": rows}


class TeamCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=63, pattern=_TEAM_NAME_RE)
    nat_alias: Optional[str] = Field(default=None, max_length=63)
    country_code: str = Field(default="XK", pattern=_COUNTRY_RE)
    is_nop: bool = False
    submit_token: Optional[str] = Field(default=None, max_length=128)


@router.post("/teams")
def api_team_create(
    body: TeamCreateBody, _: str = Depends(require_admin)
) -> Dict[str, Any]:
    import os

    token_prefix = os.getenv("TEAM_TOKEN_PREFIX", "submit-")
    token = body.submit_token or f"{token_prefix}{body.name}"
    nat_alias = body.nat_alias or f"{body.name}-nat"
    cc = body.country_code.upper()
    with get_cursor(commit=True) as (_conn, cur):
        try:
            cur.execute(
                """
                INSERT INTO teams (name, submit_token, nat_alias, is_nop, country_code)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, name, submit_token, nat_alias, is_nop, country_code, created_at;
                """,
                (body.name, token, nat_alias, body.is_nop, cc),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"create failed: {exc}")
        row = cur.fetchone()
    write_log(
        "teams",
        "Team created",
        f"{body.name} (cc={cc}, nop={body.is_nop})",
        level=LogLevel.INFO,
    )
    return _serialize_team(row)


class TeamUpdateBody(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=63, pattern=_TEAM_NAME_RE)
    nat_alias: Optional[str] = Field(default=None, max_length=63)
    country_code: Optional[str] = Field(default=None, pattern=_COUNTRY_RE)
    is_nop: Optional[bool] = None
    submit_token: Optional[str] = Field(default=None, max_length=128)


@router.patch("/teams/{team_id}")
def api_team_update(
    team_id: int,
    body: TeamUpdateBody,
    _: str = Depends(require_admin),
) -> Dict[str, Any]:
    sets: List[str] = []
    args: List[Any] = []
    if body.name is not None:
        sets.append("name = %s")
        args.append(body.name)
    if body.nat_alias is not None:
        sets.append("nat_alias = %s")
        args.append(body.nat_alias)
    if body.country_code is not None:
        sets.append("country_code = %s")
        args.append(body.country_code.upper())
    if body.is_nop is not None:
        sets.append("is_nop = %s")
        args.append(body.is_nop)
    if body.submit_token is not None:
        sets.append("submit_token = %s")
        args.append(body.submit_token)
    if not sets:
        raise HTTPException(status_code=400, detail="no fields to update")
    args.append(team_id)
    with get_cursor(commit=True) as (_conn, cur):
        try:
            cur.execute(
                f"""
                UPDATE teams SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, name, submit_token, nat_alias, is_nop, country_code, created_at;
                """,
                args,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"update failed: {exc}")
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="team not found")
    write_log(
        "teams",
        "Team updated",
        f"#{team_id} → {row['name']}",
        level=LogLevel.INFO,
    )
    return _serialize_team(row)


@router.delete("/teams/{team_id}")
def api_team_delete(
    team_id: int, _: str = Depends(require_admin)
) -> Dict[str, Any]:
    with get_cursor(commit=True) as (_conn, cur):
        cur.execute("SELECT name FROM teams WHERE id = %s;", (team_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="team not found")
        name = row["name"]
        cur.execute("DELETE FROM teams WHERE id = %s;", (team_id,))
    write_log(
        "teams",
        "Team deleted",
        f"#{team_id} ({name})",
        level=LogLevel.WARNING,
    )
    return {"ok": True, "deleted_id": team_id}


@router.post("/teams/{team_id}/rotate-token")
def api_team_rotate_token(
    team_id: int, _: str = Depends(require_admin)
) -> Dict[str, Any]:
    import secrets

    new_token = f"submit-{secrets.token_urlsafe(16)}"
    with get_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """
            UPDATE teams SET submit_token = %s
            WHERE id = %s
            RETURNING id, name, submit_token, nat_alias, is_nop, country_code, created_at;
            """,
            (new_token, team_id),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="team not found")
    write_log(
        "teams",
        "Submit token rotated",
        f"#{team_id} ({row['name']})",
        level=LogLevel.WARNING,
    )
    return _serialize_team(row)


# ---------------------------------------------------------------------------
# Network routing artifacts
# ---------------------------------------------------------------------------


@router.get("/network")
def api_network(_: str = Depends(require_admin)) -> Dict[str, Any]:
    with get_cursor(commit=True) as (_conn, cur):
        settings, plans = load_network_plans(cur)
    return {
        "settings": {
            "checker_cidr": settings.get("checker_cidr"),
            "control_public_cidr": settings.get("control_public_cidr"),
            "router_endpoint": settings.get("router_endpoint"),
            "router_listen_port": settings.get("router_listen_port"),
            "control_public_ports": settings.get("control_public_ports"),
        },
        "teams": [
            {
                "team_id": p.team_id,
                "team": p.team_name,
                "team_cidr": p.team_cidr,
                "gateway_ip": p.gateway_ip,
                "vulnbox_ip": p.vulnbox_ip,
                "player_ip": p.player_ip,
                "player_public_key": p.player_public_key,
            }
            for p in plans
        ],
        "acl_policy": [
            "checkers can reach all team networks",
            "team players can reach same-team networks",
            "team players can attack other vulnboxes",
            "team players can reach only public control ports",
            "router/control internals default to drop",
        ],
    }


@router.post("/network/sync")
def api_network_sync(_: str = Depends(require_admin)) -> Dict[str, Any]:
    with get_cursor(commit=True) as (_conn, cur):
        settings, plans = load_network_plans(cur)
    write_log("network", "Network state synchronized", f"teams={len(plans)}", LogLevel.INFO)
    return {"ok": True, "teams": len(plans), "settings": len(settings)}


@router.get("/network/export")
def api_network_export(_: str = Depends(require_admin)) -> StreamingResponse:
    with get_cursor(commit=True) as (_conn, cur):
        settings, plans = load_network_plans(cur)
    bundle = build_router_bundle(settings, plans)
    buf = BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(bundle):
            zf.writestr(name, bundle[name])
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="kossim-router-bundle.zip"'},
    )


# ---------------------------------------------------------------------------
# Vulnboxes
# ---------------------------------------------------------------------------


class VulnboxActionBody(BaseModel):
    action: str = Field(pattern="^(start|stop|restart|reset|rebuild)$")


class VulnboxStatusBody(BaseModel):
    status: str = Field(min_length=1, max_length=32)
    message: str = Field(default="", max_length=2000)


@router.get("/vulnboxes")
def api_vulnboxes(_: str = Depends(require_admin)) -> Dict[str, Any]:
    with get_cursor(commit=True) as (_conn, cur):
        ensure_vulnboxes(cur)
        cur.execute(
            """
            SELECT vb.*, t.name AS team
            FROM vulnboxes vb
            JOIN teams t ON t.id = vb.team_id
            ORDER BY t.is_nop ASC, t.name ASC;
            """
        )
        rows = [serialize_vulnbox(dict(r)) for r in cur.fetchall()]
        cur.execute(
            """
            SELECT ve.created_at, t.name AS team, ve.action, ve.status, ve.message
            FROM vulnbox_events ve
            LEFT JOIN teams t ON t.id = ve.team_id
            ORDER BY ve.created_at DESC
            LIMIT 80;
            """
        )
        events = [
            {
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "team": r["team"],
                "action": r["action"],
                "status": r["status"],
                "message": r["message"],
            }
            for r in cur.fetchall()
        ]
    return {"rows": rows, "events": events}


@router.post("/vulnboxes/sync")
def api_vulnboxes_sync(_: str = Depends(require_admin)) -> Dict[str, Any]:
    with get_cursor(commit=True) as (_conn, cur):
        ensure_vulnboxes(cur)
        cur.execute("SELECT COUNT(*) AS n FROM vulnboxes;")
        count = int(cur.fetchone()["n"] or 0)
    write_log("vulnboxes", "Vulnbox desired state synchronized", f"count={count}", LogLevel.INFO)
    return {"ok": True, "count": count}


@router.post("/vulnboxes/{vulnbox_id}/action")
def api_vulnbox_action(
    vulnbox_id: int,
    body: VulnboxActionBody,
    _: str = Depends(require_admin),
) -> Dict[str, Any]:
    if body.action not in VALID_ACTIONS:
        raise HTTPException(status_code=400, detail="unsupported action")
    counter_col = {
        "restart": "restart_generation",
        "reset": "reset_generation",
        "rebuild": "rebuild_generation",
    }.get(body.action)
    desired_status = "STOPPED" if body.action == "stop" else "RUNNING"
    with get_cursor(commit=True) as (_conn, cur):
        if counter_col:
            cur.execute(
                f"""
                UPDATE vulnboxes
                SET desired_status = %s, {counter_col} = {counter_col} + 1, updated_at = NOW()
                WHERE id = %s
                RETURNING team_id;
                """,
                (desired_status, vulnbox_id),
            )
        else:
            cur.execute(
                """
                UPDATE vulnboxes
                SET desired_status = %s, updated_at = NOW()
                WHERE id = %s
                RETURNING team_id;
                """,
                (desired_status, vulnbox_id),
            )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="vulnbox not found")
        record_vulnbox_event(
            cur,
            vulnbox_id=vulnbox_id,
            team_id=int(row["team_id"]),
            action=body.action,
            status="QUEUED",
            message="operator requested action",
        )
    try:
        task_id = enqueue_vulnbox_action(vulnbox_id, body.action)
    except Exception as exc:
        with get_cursor(commit=True) as (_conn, cur):
            record_vulnbox_event(
                cur,
                vulnbox_id=vulnbox_id,
                team_id=None,
                action=body.action,
                status="FAILED",
                message=f"enqueue failed: {exc!r}",
            )
        raise HTTPException(status_code=503, detail=f"queue unavailable: {exc}")
    return {"ok": True, "task_id": task_id}


@router.post("/vulnboxes/{vulnbox_id}/status")
def api_vulnbox_status(
    vulnbox_id: int,
    body: VulnboxStatusBody,
    _: str = Depends(require_admin),
) -> Dict[str, Any]:
    with get_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """
            UPDATE vulnboxes
            SET observed_status = %s, last_report_at = NOW(), updated_at = NOW()
            WHERE id = %s
            RETURNING team_id;
            """,
            (body.status.upper(), vulnbox_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="vulnbox not found")
        record_vulnbox_event(
            cur,
            vulnbox_id=vulnbox_id,
            team_id=int(row["team_id"]),
            action="status",
            status=body.status.upper(),
            message=body.message,
        )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------


@router.get("/observability")
def api_observability(
    ticks: int = Query(default=60, ge=2, le=500),
    _: str = Depends(require_admin),
) -> Dict[str, Any]:
    with get_cursor(commit=False) as (_conn, cur):
        return build_observability(cur, ticks=ticks)


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


@router.get("/logs")
def api_logs(
    level: Optional[str] = None,
    component: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(default=200, ge=1, le=1000),
    _: str = Depends(require_admin),
) -> Dict[str, Any]:
    level_int = _opt_int(level)
    where = ["1=1"]
    args: List[Any] = []
    if level_int is not None:
        where.append("lm.level >= %s")
        args.append(level_int)
    if component:
        where.append("lm.component = %s")
        args.append(component)
    if q:
        where.append("(lm.title ILIKE %s OR lm.text ILIKE %s)")
        like = f"%{q}%"
        args.extend([like, like])
    args.append(limit)
    with get_cursor(commit=False) as (_conn, cur):
        cur.execute(
            f"""
            SELECT lm.created_at, lm.component, lm.level, lm.title, lm.text
            FROM log_messages lm
            WHERE {' AND '.join(where)}
            ORDER BY lm.created_at DESC
            LIMIT %s;
            """,
            args,
        )
        rows = [
            {
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "component": r["component"],
                "level": int(r["level"]),
                "level_label": LEVEL_LABELS.get(LogLevel(r["level"]), "INFO")
                if r["level"] in [e.value for e in LogLevel]
                else "INFO",
                "title": r["title"],
                "text": r["text"] or "",
            }
            for r in cur.fetchall()
        ]
        cur.execute("SELECT DISTINCT component FROM log_messages ORDER BY component;")
        components = [r["component"] for r in cur.fetchall()]
    return {
        "rows": rows,
        "components": components,
        "levels": [{"value": int(l), "label": LEVEL_LABELS[l]} for l in LogLevel],
    }
