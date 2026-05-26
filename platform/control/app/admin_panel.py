"""Data helpers for the operator admin.

Previously this module also served HTML admin pages. Those have been removed
in favor of the React SPA, which talks to the JSON endpoints in
``admin_api.py``. The helpers below remain because ``admin_api.py`` imports
them.
"""

from __future__ import annotations

from typing import Any, Dict

from .db import get_cursor
from .flag_crypto import decode_flag
from .flag_submit import _current_tick, _game_running, _retention_ticks
from .game_timer import load_timer


def _game_summary() -> Dict[str, Any]:
    with get_cursor(commit=False) as (_conn, cur):
        timer = load_timer(cur)
        timer.sync_scheduled_start(cur)
        timer.load(cur)
        cur.execute("SELECT COUNT(*) AS n FROM submissions WHERE result = 'accepted';")
        accepted = int(cur.fetchone()["n"])
        cur.execute("SELECT COUNT(*) AS n FROM submissions;")
        total_sub = int(cur.fetchone()["n"])
        cur.execute(
            """
            SELECT COUNT(*) AS n FROM service_health sh
            WHERE sh.tick = %s AND sh.status NOT IN ('SUCCESS', 'RECOVERING');
            """,
            (max(1, timer.current_tick),),
        )
        bad_checkers = int(cur.fetchone()["n"] or 0)
    return {
        "timer": timer.to_api_dict(),
        "accepted_submissions": accepted,
        "total_submissions": total_sub,
        "bad_checkers": bad_checkers,
    }


def _submission_chart_data(limit_ticks: int = 24) -> Dict[str, Any]:
    with get_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """
            SELECT tick_issued AS tick, result, COUNT(*) AS n
            FROM submissions
            WHERE tick_issued IS NOT NULL
            GROUP BY tick_issued, result
            ORDER BY tick_issued DESC
            LIMIT 200;
            """
        )
        rows = cur.fetchall()
    ticks = sorted({int(r["tick"]) for r in rows if r["tick"] is not None}, reverse=True)[:limit_ticks]
    ticks.sort()
    results = sorted({r["result"] for r in rows})
    datasets = []
    colors = {
        "accepted": "#34d399",
        "duplicate": "#94a3b8",
        "expired": "#f87171",
        "invalid": "#fb923c",
        "own_flag": "#fbbf24",
    }
    by_tick: Dict[int, Dict[str, int]] = {t: {} for t in ticks}
    for r in rows:
        if r["tick"] is None:
            continue
        t = int(r["tick"])
        if t not in by_tick:
            continue
        by_tick[t][r["result"]] = int(r["n"])
    for res in results:
        datasets.append(
            {
                "label": res,
                "data": [by_tick.get(t, {}).get(res, 0) for t in ticks],
                "backgroundColor": colors.get(res, "#64748b"),
            }
        )
    return {"labels": [str(t) for t in ticks], "datasets": datasets}


def _checker_status_chart_data() -> Dict[str, Any]:
    with get_cursor(commit=False) as (_conn, cur):
        timer = load_timer(cur)
        tick = max(1, timer.current_tick)
        cur.execute(
            """
            SELECT status, COUNT(*) AS n
            FROM service_health
            WHERE tick = %s
            GROUP BY status;
            """,
            (tick,),
        )
        rows = cur.fetchall()
    labels = [r["status"] for r in rows]
    data = [int(r["n"]) for r in rows]
    colors = {
        "SUCCESS": "#34d399",
        "RECOVERING": "#fbbf24",
        "MUMBLE": "#fb923c",
        "OFFLINE": "#f87171",
        "CRASHED": "#c084fc",
    }
    return {
        "labels": labels,
        "datasets": [
            {"data": data, "backgroundColor": [colors.get(l, "#64748b") for l in labels]}
        ],
    }


def _decode_flag_report(flag: str) -> Dict[str, Any]:
    info = decode_flag(flag.strip())
    if info is None:
        return {"valid": False, "error": "HMAC verification failed or malformed flag"}
    with get_cursor(commit=False) as (_conn, cur):
        cur.execute("SELECT name FROM teams WHERE id = %s;", (info.team_id,))
        tr = cur.fetchone()
        cur.execute("SELECT name FROM services WHERE id = %s;", (info.service_id,))
        sr = cur.fetchone()
        cur.execute(
            "SELECT result, is_firstblood FROM submissions WHERE flag = %s LIMIT 1;",
            (flag.strip(),),
        )
        sub = cur.fetchone()
        tick_now = _current_tick(cur)
        retention = _retention_ticks()
        running = _game_running(cur)
    team_name = tr["name"] if tr else f"id={info.team_id}"
    service_name = sr["name"] if sr else f"id={info.service_id}"
    oldest = max(1, tick_now - retention + 1)
    verdict = "would accept"
    if not running:
        verdict = "CTF not running"
    elif info.tick < oldest:
        verdict = "expired"
    elif info.tick > tick_now:
        verdict = "future tick"
    elif sub:
        verdict = f"already submitted ({sub['result']})"
    return {
        "valid": True,
        "tick": info.tick,
        "team": team_name,
        "service": service_name,
        "payload": info.payload,
        "verdict": verdict,
        "submitted_before": bool(sub),
        "is_firstblood": bool(sub["is_firstblood"]) if sub else False,
    }
