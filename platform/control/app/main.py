from __future__ import annotations

import datetime as dt
import html
import os
import time
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .db import get_cursor
from .debug_api import build_debug_router
from .eno_checker import derive_method_statuses, is_up as checker_is_up
from .game_api import router as game_api_router
from .game_timer import load_timer
from .init_db import bootstrap_database
from .networking import build_router_bundle, load_network_plans
from .observability import build_observability, render_prometheus_metrics
from .scoreboard_api import build_scoreboard_router
from .vulnboxes import record_vulnbox_event
from .spa import mount_spa
from .team_api import build_team_router
from .tcp_flag_server import start_tcp_server_background
from .access import (
    effective_freeze_tick,
    request_is_internal as _request_is_internal,
    require_internal as _require_internal,
)
from .admin_auth import install_session_middleware
from .admin_api import router as admin_api_router
from .patches_api import (
    admin_router as patches_admin_router,
    bootstrap_patches_table,
    build_public_patches_router,
)
from .wiki_api import (
    admin_router as wiki_admin_router,
    bootstrap_wiki_table,
    build_public_wiki_router,
)


app = FastAPI(title="KosSim Control Plane", version="0.1.0")
install_session_middleware(app)
app.include_router(admin_api_router)
app.include_router(patches_admin_router)
app.include_router(wiki_admin_router)
app.include_router(build_public_patches_router())
app.include_router(build_public_wiki_router())
app.include_router(game_api_router)
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _effective_freeze_tick() -> Optional[int]:
    return effective_freeze_tick()


def _stats_at_tick(tick: int, include_nop: bool = False) -> Dict[int, Dict[int, Dict[str, float]]]:
    stats: Dict[int, Dict[int, Dict[str, float]]] = {}
    with get_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """
            SELECT ss.team_id,
                   ss.service_id,
                   ss.attack_points,
                   ss.defense_points,
                   ss.uptime_points,
                   ss.hacked_penalty_points,
                   ss.challenge_points,
                   ss.service_total,
                   ss.flags_captured,
                   ss.attackers_count,
                   ss.victims_count,
                   ss.sla_up_count,
                   ss.sla_total_count
            FROM score_snapshots ss
            JOIN flag_rounds fr ON fr.round_id = ss.round_id
            JOIN teams t ON t.id = ss.team_id
            WHERE fr.tick = %s
              AND (%s = TRUE OR t.is_nop = FALSE);
            """,
            (tick, include_nop),
        )
        for row in cur.fetchall():
            stats.setdefault(row["team_id"], {})[row["service_id"]] = {
                "attack_points": _points(row["attack_points"]),
                "defense_points": _points(row["defense_points"]),
                "uptime_points": _points(row["uptime_points"]),
                "hacked_penalty_points": 0.0,
                "challenge_points": _points(row["challenge_points"]),
                "service_total": _points(row["service_total"]),
                "flags_captured": int(row["flags_captured"] or 0),
                "victims_count": int(row["victims_count"] or 0),
                "attackers_count": int(row["attackers_count"] or 0),
                "sla_up_count": int(row["sla_up_count"] or 0),
                "sla_total_count": int(row["sla_total_count"] or 1),
            }
    return stats


def _scoreboard_rows_at_tick(tick: int, include_nop: bool = False) -> List[Dict[str, Any]]:
    with get_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """
            SELECT t.id AS team_id, t.name AS team_name, t.nat_alias, t.is_nop,
                   t.country_code,
                   COALESCE(SUM(ss.attack_points), 0) AS attack_points,
                   COALESCE(SUM(ss.defense_points), 0) AS defense_points,
                   COALESCE(SUM(ss.uptime_points), 0) AS uptime_points,
                   COALESCE(SUM(ss.hacked_penalty_points), 0) AS hacked_penalty_points,
                   COALESCE(SUM(ss.challenge_points), 0) AS challenge_points,
                   1::numeric AS sla_points,
                   COALESCE(SUM(ss.service_total), 0) AS total,
                   MAX(ss.created_at) AS updated_at
            FROM teams t
            LEFT JOIN flag_rounds fr ON fr.tick = %s
            LEFT JOIN score_snapshots ss
              ON ss.team_id = t.id AND ss.round_id = fr.round_id
            WHERE (%s = TRUE OR t.is_nop = FALSE)
            GROUP BY t.id, t.name, t.nat_alias, t.is_nop, t.country_code
            ORDER BY total DESC, t.name ASC;
            """,
            (tick, include_nop),
        )
        return [dict(row) for row in cur.fetchall()]


def _submission_points() -> int:
    return int(os.getenv("SUBMISSION_POINTS", "1"))


def _score_weights() -> Dict[str, float]:
    return {
        "attack_points": float(os.getenv("ATTACK_POINTS", "10")),
        "defense_success_points": float(os.getenv("DEFENSE_SUCCESS_POINTS", "5")),
        "uptime_points": float(os.getenv("UPTIME_POINTS", "2")),
        "hacked_penalty_points": float(os.getenv("HACKED_PENALTY_POINTS", "10")),
    }


def _rotation_seconds() -> int:
    return int(os.getenv("ROTATION_SECONDS", "120"))


def _retention_ticks() -> int:
    return max(1, int(os.getenv("FLAG_RETENTION_TICKS", "5")))


def _scoreboard_logo_url() -> str:
    return os.getenv("SCOREBOARD_LOGO_URL", "/static/kct-logo.png")


def _max_accepted_per_round() -> int:
    # 0 means unlimited accepted flags per round.
    return int(os.getenv("MAX_ACCEPTED_PER_TEAM_PER_ROUND", "0"))


def _points(value: Any) -> float:
    return round(float(value or 0), 4)


def _current_round_id(now: Optional[float] = None) -> int:
    ts = now if now is not None else time.time()
    return int(ts // _rotation_seconds())


def _first_round_id() -> Optional[int]:
    with get_cursor(commit=False) as (_conn, cur):
        cur.execute("SELECT MIN(round_id) AS first_round_id FROM flag_rounds;")
        row = cur.fetchone()
        if not row or row["first_round_id"] is None:
            return None
        return int(row["first_round_id"])


def _display_round_number(current_round_id: int, first_round_id: Optional[int]) -> int:
    if first_round_id is None:
        return 1
    return max(1, int(current_round_id - first_round_id + 1))


def _scoreboard_rows(include_nop: bool = False) -> List[Dict[str, Any]]:
    with get_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """
            SELECT
                t.id AS team_id,
                t.name AS team_name,
                t.nat_alias,
                t.is_nop,
                t.country_code,
                s.attack_points,
                s.defense_points,
                s.uptime_points,
                s.hacked_penalty_points,
                s.challenge_points,
                s.sla_points,
                s.total,
                s.updated_at
            FROM teams t
            JOIN scores s ON s.team_id = t.id
            WHERE (%s = TRUE OR t.is_nop = FALSE)
            ORDER BY s.total DESC, t.name ASC;
            """,
            (include_nop,),
        )
        return [dict(row) for row in cur.fetchall()]


def _services_list() -> List[Dict[str, Any]]:
    with get_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """
            SELECT
                id,
                name AS slug,
                COALESCE(NULLIF(display_name, ''), name) AS name,
                COALESCE(NULLIF(display_name, ''), name) AS display_name
            FROM services
            ORDER BY id ASC;
            """
        )
        return [dict(row) for row in cur.fetchall()]


def _service_label(service: Dict[str, Any]) -> str:
    return str(service.get("display_name") or service.get("name") or "")


def _per_service_stats(include_nop: bool = False) -> Dict[int, Dict[int, Dict[str, float]]]:
    """Return cumulative current stats per (team_id, service_id).

    Each service contributes attack and defense components. ``uptime_points``
    carries the SLA multiplier for compatibility with the existing API shape.
    """
    stats: Dict[int, Dict[int, Dict[str, float]]] = {}
    with get_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """
            WITH attack_agg AS (
                SELECT s.submitter_team_id AS team_id,
                       s.service_id,
                       SUM(%(attack_points)s / GREATEST(svc.flags_per_tick, 1)) AS attack_points,
                       COUNT(*) AS flags_captured,
                       COUNT(DISTINCT s.target_team_id) AS victims_count
                FROM submissions s
                JOIN services svc ON svc.id = s.service_id
                WHERE s.result = 'accepted'
                GROUP BY s.submitter_team_id, s.service_id
            ),
            attackers_agg AS (
                SELECT target_team_id AS team_id,
                       service_id,
                       COUNT(DISTINCT submitter_team_id) AS attackers_count
                FROM submissions
                WHERE result = 'accepted'
                GROUP BY target_team_id, service_id
            ),
            defense_agg AS (
                SELECT h.team_id,
                       h.service_id,
                       COUNT(*) * %(defense_success_points)s * GREATEST(svc.flags_per_tick, 1) AS defense_points
                FROM service_health h
                JOIN services svc ON svc.id = h.service_id
                WHERE h.is_up = TRUE
                  AND NOT EXISTS (
                      SELECT 1
                      FROM submissions s
                      WHERE s.result = 'accepted'
                        AND s.target_team_id = h.team_id
                        AND s.service_id = h.service_id
                        AND s.round_id = h.round_id
                  )
                GROUP BY h.team_id, h.service_id
            ),
            sla_agg AS (
                SELECT team_id,
                       service_id,
                       SUM(CASE WHEN is_up THEN 1 ELSE 0 END) AS up_count,
                       COUNT(*) AS total_count,
                       CASE WHEN COUNT(*) = 0 THEN 0
                            ELSE SUM(CASE WHEN is_up THEN 1 ELSE 0 END)::numeric / COUNT(*)
                       END AS sla_multiplier
                FROM service_health
                GROUP BY team_id, service_id
            )
            SELECT
                ts.team_id,
                ts.service_id,
                COALESCE(att.attack_points, 0) AS attack_points,
                COALESCE(def.defense_points, 0) AS defense_points,
                COALESCE(sla.sla_multiplier, 0) AS uptime_points,
                0 AS hacked_penalty_points,
                (
                    COALESCE(att.attack_points, 0)
                    + COALESCE(def.defense_points, 0)
                ) AS challenge_points,
                (
                    COALESCE(att.attack_points, 0)
                    + COALESCE(def.defense_points, 0)
                ) * COALESCE(sla.sla_multiplier, 0) AS service_total,
                COALESCE(att.flags_captured, 0) AS flags_captured,
                COALESCE(att.victims_count, 0) AS victims_count,
                COALESCE(atk.attackers_count, 0) AS attackers_count,
                COALESCE(sla.up_count, 0) AS sla_up_count,
                COALESCE(sla.total_count, 0) AS sla_total_count
            FROM team_services ts
            JOIN teams t ON t.id = ts.team_id
            LEFT JOIN attack_agg    att  ON att.team_id = ts.team_id AND att.service_id = ts.service_id
            LEFT JOIN attackers_agg atk  ON atk.team_id = ts.team_id AND atk.service_id = ts.service_id
            LEFT JOIN defense_agg   def  ON def.team_id = ts.team_id AND def.service_id = ts.service_id
            LEFT JOIN sla_agg       sla  ON sla.team_id = ts.team_id AND sla.service_id = ts.service_id
            WHERE (%(include_nop)s = TRUE OR t.is_nop = FALSE);
            """,
            {"include_nop": include_nop, **_score_weights()},
        )
        for row in cur.fetchall():
            stats.setdefault(row["team_id"], {})[row["service_id"]] = {
                "attack_points": _points(row["attack_points"]),
                "defense_points": _points(row["defense_points"]),
                "uptime_points": _points(row["uptime_points"]),
                "hacked_penalty_points": _points(row["hacked_penalty_points"]),
                "challenge_points": _points(row["challenge_points"]),
                "service_total": _points(row["service_total"]),
                "flags_captured": int(row["flags_captured"]),
                "victims_count": int(row["victims_count"]),
                "attackers_count": int(row["attackers_count"]),
                "sla_up_count": int(row["sla_up_count"]),
                "sla_total_count": int(row["sla_total_count"]),
            }
    return stats


def _previous_tick_snapshots(
    current_tick: Optional[int],
) -> Dict[int, Dict[int, Dict[str, float]]]:
    """Return the snapshot from the tick BEFORE ``current_tick``.

    The rotator writes a fresh ``score_snapshots`` row each tick, so picking
    the latest one per (team, service) returns the *current* tick — which
    yields a zero delta. To compute "points earned this tick" we need the
    snapshot from one tick earlier. Returns an empty dict for tick 1 (no
    prior snapshot exists), which makes the delta default to the full
    cumulative total — i.e., everything was earned in this first tick.
    """
    snaps: Dict[int, Dict[int, Dict[str, float]]] = {}
    if current_tick is None or current_tick <= 1:
        return snaps
    prev_tick = current_tick - 1
    with get_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """
            SELECT ss.team_id,
                   ss.service_id,
                   ss.attack_points,
                   ss.defense_points,
                   ss.uptime_points,
                   ss.hacked_penalty_points,
                   ss.challenge_points,
                   ss.service_total,
                   ss.flags_captured,
                   ss.attackers_count,
                   ss.victims_count,
                   ss.sla_up_count,
                   ss.sla_total_count
            FROM score_snapshots ss
            JOIN flag_rounds fr ON fr.round_id = ss.round_id
            WHERE fr.tick = %s;
            """,
            (prev_tick,),
        )
        for row in cur.fetchall():
            snaps.setdefault(row["team_id"], {})[row["service_id"]] = {
                "attack_points": _points(row["attack_points"]),
                "defense_points": _points(row["defense_points"]),
                "uptime_points": _points(row["uptime_points"]),
                "hacked_penalty_points": _points(row["hacked_penalty_points"]),
                "challenge_points": _points(row["challenge_points"]),
                "service_total": _points(row["service_total"]),
                "flags_captured": int(row["flags_captured"]),
                "attackers_count": int(row["attackers_count"]),
                "victims_count": int(row["victims_count"]),
                "sla_up_count": int(row["sla_up_count"]),
                "sla_total_count": int(row["sla_total_count"]),
            }
    return snaps


def _latest_scored_tick(current_tick: Optional[int]) -> Optional[int]:
    """Return the newest tick with scoreboard snapshots at or before current_tick.

    The game timer advances before the rotator has necessarily completed all
    checker work and score snapshot writes for that new tick. During that
    small window, rendering ``current_tick`` directly creates a table full of
    zero service cells. Keep showing the latest completed score snapshot until
    the new tick has real data.
    """
    with get_cursor(commit=False) as (_conn, cur):
        if current_tick is None:
            cur.execute(
                """
                SELECT MAX(fr.tick) AS tick
                FROM score_snapshots ss
                JOIN flag_rounds fr ON fr.round_id = ss.round_id;
                """
            )
        else:
            cur.execute(
                """
                SELECT MAX(fr.tick) AS tick
                FROM score_snapshots ss
                JOIN flag_rounds fr ON fr.round_id = ss.round_id
                WHERE fr.tick <= %s;
                """,
                (current_tick,),
            )
        row = cur.fetchone()
    if not row or row["tick"] is None:
        return None
    return int(row["tick"])


def _service_top_team(
    rows_with_cells: List[Dict[str, Any]],
    service_id: int,
    first_blood: Optional[Dict[str, Any]] = None,
    activity: Optional[Dict[str, int]] = None,
) -> Optional[Dict[str, Any]]:
    """Pick the team with the highest total score on a service."""
    best: Optional[Dict[str, Any]] = None
    best_score = -1
    for row in rows_with_cells:
        cell = row["service_cells"].get(service_id)
        if not cell:
            continue
        if cell["service_total"] > best_score:
            best_score = cell["service_total"]
            best = {
                "team_name": row["team_name"],
                "country_code": row["country_code"],
                "attackers_count": cell["attackers_count"],
                "victims_count": cell["victims_count"],
                "service_total": cell["service_total"],
            }
    activity_attackers = int((activity or {}).get("attackers_count") or 0)
    activity_victims = int((activity or {}).get("victims_count") or 0)
    if best is not None:
        best["attackers_count"] = activity_attackers
        best["victims_count"] = activity_victims
    if best is None or (
        best_score <= 0
        and activity_attackers <= 0
        and activity_victims <= 0
        and first_blood is None
    ):
        if not first_blood:
            return None
        best = {
            "team_name": first_blood["attacker_team"],
            "country_code": first_blood["attacker_country"] or "XK",
            "attackers_count": max(activity_attackers, 1),
            "victims_count": max(activity_victims, 1 if first_blood.get("victim_team") else 0),
            "service_total": 0,
        }
    best["first_blood"] = first_blood
    return best


def _service_first_bloods(include_nop: bool = False) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    with get_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """
            SELECT DISTINCT ON (sub.service_id)
                sub.id,
                sub.submitted_at,
                sub.tick_issued,
                sub.payload,
                svc.id AS service_id,
                svc.name AS service_slug,
                COALESCE(NULLIF(svc.display_name, ''), svc.name) AS service_name,
                COALESCE(NULLIF(svc.display_name, ''), svc.name) AS service_display_name,
                attacker.name AS attacker_team,
                attacker.country_code AS attacker_country,
                victim.name AS victim_team,
                victim.country_code AS victim_country
            FROM submissions sub
            JOIN services svc ON svc.id = sub.service_id
            JOIN teams attacker ON attacker.id = sub.submitter_team_id
            LEFT JOIN teams victim ON victim.id = sub.target_team_id
            WHERE sub.result = 'accepted'
              AND sub.is_firstblood = TRUE
              AND (%s = TRUE OR attacker.is_nop = FALSE)
              AND (%s = TRUE OR victim.id IS NULL OR victim.is_nop = FALSE)
            ORDER BY sub.service_id, sub.submitted_at ASC, sub.id ASC;
            """,
            (include_nop, include_nop),
        )
        for row in cur.fetchall():
            out[int(row["service_id"])] = {
                "id": int(row["id"]),
                "timestamp": row["submitted_at"].timestamp() if row["submitted_at"] else None,
                "service_id": int(row["service_id"]),
                "service_name": row["service_name"],
                "service_slug": row["service_slug"],
                "service_display_name": row["service_display_name"],
                "attacker_team": row["attacker_team"],
                "attacker_country": row["attacker_country"],
                "victim_team": row["victim_team"],
                "victim_country": row["victim_country"],
                "tick_issued": row["tick_issued"],
                "payload": row["payload"],
            }
    return out


def _service_activity_counts(include_nop: bool = False) -> Dict[int, Dict[str, int]]:
    out: Dict[int, Dict[str, int]] = {}
    with get_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """
            SELECT
                sub.service_id,
                COUNT(DISTINCT sub.submitter_team_id) AS attackers_count,
                COUNT(DISTINCT sub.target_team_id) AS victims_count
            FROM submissions sub
            JOIN teams attacker ON attacker.id = sub.submitter_team_id
            LEFT JOIN teams victim ON victim.id = sub.target_team_id
            WHERE sub.result = 'accepted'
              AND (%s = TRUE OR attacker.is_nop = FALSE)
              AND (%s = TRUE OR victim.id IS NULL OR victim.is_nop = FALSE)
            GROUP BY sub.service_id;
            """,
            (include_nop, include_nop),
        )
        for row in cur.fetchall():
            out[int(row["service_id"])] = {
                "attackers_count": int(row["attackers_count"] or 0),
                "victims_count": int(row["victims_count"] or 0),
            }
    return out


def _country_flag_emoji(code: str) -> str:
    code = (code or "").upper().strip()
    if len(code) != 2 or not code.isalpha():
        return "🏴"
    # Kosovo (XK) has no canonical regional indicator pair; fall back to a generic flag
    # so terminals/browsers without a Kosovo glyph still render something.
    if code == "XK":
        return "🇽🇰"
    return chr(0x1F1E6 + ord(code[0]) - ord("A")) + chr(0x1F1E6 + ord(code[1]) - ord("A"))


def _delta(current: Any, previous: Any) -> Any:
    return current - previous


def _sla_pct(up: int, total: int) -> float:
    if total <= 0:
        return 100.0
    return round((up / total) * 100.0, 2)


def _checker_status_at_tick(
    tick: int,
) -> Dict[tuple[int, int], Dict[str, Any]]:
    """Latest checker status + flag_avail per (team_id, service_id) for a tick."""
    out: Dict[tuple[int, int], Dict[str, Any]] = {}
    with get_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """
            SELECT DISTINCT ON (sh.team_id, sh.service_id)
                sh.team_id, sh.service_id, sh.status, sh.flag_avail
            FROM service_health sh
            WHERE sh.tick = %s
            ORDER BY sh.team_id, sh.service_id, sh.checked_at DESC;
            """,
            (tick,),
        )
        for row in cur.fetchall():
            out[(int(row["team_id"]), int(row["service_id"]))] = {
                "status": row["status"] or "OFFLINE",
                "flag_avail": row["flag_avail"] or {},
            }
    return out


def _tick_activity(
    tick: Optional[int],
    *,
    include_nop: bool = False,
    limit: int = 24,
) -> Dict[str, Any]:
    if tick is None:
        return {
            "tick": None,
            "capture_count": 0,
            "first_blood_count": 0,
            "attackers_count": 0,
            "victims_count": 0,
            "captures": [],
            "first_bloods": [],
        }

    limit = max(1, min(limit, 100))
    with get_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """
            SELECT
                COUNT(*) AS capture_count,
                COUNT(*) FILTER (WHERE sub.is_firstblood = TRUE) AS first_blood_count,
                COUNT(DISTINCT sub.submitter_team_id) AS attackers_count,
                COUNT(DISTINCT sub.target_team_id) AS victims_count
            FROM submissions sub
            JOIN flag_rounds fr ON fr.tick = %s
            JOIN teams attacker ON attacker.id = sub.submitter_team_id
            LEFT JOIN teams victim ON victim.id = sub.target_team_id
            WHERE sub.result = 'accepted'
              AND sub.submitted_at >= fr.starts_at
              AND sub.submitted_at < fr.ends_at
              AND (%s = TRUE OR attacker.is_nop = FALSE)
              AND (%s = TRUE OR victim.id IS NULL OR victim.is_nop = FALSE);
            """,
            (tick, include_nop, include_nop),
        )
        counts = cur.fetchone() or {}
        cur.execute(
            """
            SELECT
                sub.id,
                sub.submitted_at,
                sub.tick_issued,
                sub.payload,
                sub.is_firstblood,
                attacker.name AS attacker_team,
                attacker.country_code AS attacker_country,
                victim.name AS victim_team,
                victim.country_code AS victim_country,
                svc.id AS service_id,
                svc.name AS service_slug,
                COALESCE(NULLIF(svc.display_name, ''), svc.name) AS service_name,
                COALESCE(NULLIF(svc.display_name, ''), svc.name) AS service_display_name
            FROM submissions sub
            JOIN flag_rounds fr ON fr.tick = %s
            JOIN teams attacker ON attacker.id = sub.submitter_team_id
            LEFT JOIN teams victim ON victim.id = sub.target_team_id
            LEFT JOIN services svc ON svc.id = sub.service_id
            WHERE sub.result = 'accepted'
              AND sub.submitted_at >= fr.starts_at
              AND sub.submitted_at < fr.ends_at
              AND (%s = TRUE OR attacker.is_nop = FALSE)
              AND (%s = TRUE OR victim.id IS NULL OR victim.is_nop = FALSE)
            ORDER BY sub.submitted_at DESC, sub.id DESC
            LIMIT %s;
            """,
            (tick, include_nop, include_nop, limit),
        )
        rows = cur.fetchall()
        cur.execute(
            """
            SELECT
                sub.id,
                sub.submitted_at,
                sub.tick_issued,
                sub.payload,
                sub.is_firstblood,
                attacker.name AS attacker_team,
                attacker.country_code AS attacker_country,
                victim.name AS victim_team,
                victim.country_code AS victim_country,
                svc.id AS service_id,
                svc.name AS service_slug,
                COALESCE(NULLIF(svc.display_name, ''), svc.name) AS service_name,
                COALESCE(NULLIF(svc.display_name, ''), svc.name) AS service_display_name
            FROM submissions sub
            JOIN flag_rounds fr ON fr.tick = %s
            JOIN teams attacker ON attacker.id = sub.submitter_team_id
            LEFT JOIN teams victim ON victim.id = sub.target_team_id
            LEFT JOIN services svc ON svc.id = sub.service_id
            WHERE sub.result = 'accepted'
              AND sub.is_firstblood = TRUE
              AND sub.submitted_at >= fr.starts_at
              AND sub.submitted_at < fr.ends_at
              AND (%s = TRUE OR attacker.is_nop = FALSE)
              AND (%s = TRUE OR victim.id IS NULL OR victim.is_nop = FALSE)
            ORDER BY sub.submitted_at DESC, sub.id DESC
            LIMIT 8;
            """,
            (tick, include_nop, include_nop),
        )
        first_rows = cur.fetchall()

    def event_from_row(r: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": int(r["id"]),
            "timestamp": r["submitted_at"].timestamp() if r["submitted_at"] else None,
            "attacker_team": r["attacker_team"],
            "attacker_country": r["attacker_country"],
            "victim_team": r["victim_team"],
            "victim_country": r["victim_country"],
            "service_id": int(r["service_id"]) if r["service_id"] is not None else None,
            "service_name": r["service_name"],
            "service_slug": r["service_slug"],
            "service_display_name": r["service_display_name"],
            "tick_issued": r["tick_issued"],
            "payload": r["payload"],
            "is_firstblood": bool(r["is_firstblood"]),
        }

    captures = [event_from_row(r) for r in rows]
    first_bloods = [event_from_row(r) for r in first_rows]
    return {
        "tick": tick,
        "capture_count": int(counts.get("capture_count") or 0),
        "first_blood_count": int(counts.get("first_blood_count") or 0),
        "attackers_count": int(counts.get("attackers_count") or 0),
        "victims_count": int(counts.get("victims_count") or 0),
        "captures": captures,
        "first_bloods": first_bloods,
    }


def _sla_badge(cell: Dict[str, Any]) -> tuple[str, str]:
    """Badge label and CSS class from current-tick checker status."""
    status = (cell.get("checker_status") or "OFFLINE").upper()
    if checker_is_up(status):
        if status == "RECOVERING":
            return "REC", "badge-warn"
        return "UP", "badge-up"
    if status in ("MUMBLE", "FLAGMISSING"):
        return status[:6], "badge-down"
    return "DOWN", "badge-down"


def _build_scoreboard_data(
    include_nop: bool = False,
    *,
    frozen: bool = False,
) -> Dict[str, Any]:
    freeze_tick = _effective_freeze_tick() if frozen else None
    if freeze_tick is not None:
        display_tick: Optional[int] = _latest_scored_tick(freeze_tick)
    else:
        with get_cursor(commit=False) as (_conn, cur):
            timer = load_timer(cur)
            timer.load(cur)
            current_tick = timer.current_tick if timer.current_tick >= 1 else None
        display_tick = _latest_scored_tick(current_tick)

    if display_tick is not None:
        teams = _scoreboard_rows_at_tick(display_tick, include_nop=include_nop)
        cur_stats = _stats_at_tick(display_tick, include_nop=include_nop)
    else:
        teams = _scoreboard_rows(include_nop=include_nop)
        cur_stats = _per_service_stats(include_nop=include_nop)
    snaps = _previous_tick_snapshots(display_tick)
    services = _services_list()
    checker_statuses = _checker_status_at_tick(display_tick) if display_tick else {}

    rows: List[Dict[str, Any]] = []
    for rank, team in enumerate(teams, start=1):
        team_id = team["team_id"]
        team_cur = cur_stats.get(team_id, {})
        team_snap = snaps.get(team_id, {})

        service_cells: Dict[int, Dict[str, Any]] = {}
        total_attack = 0.0
        total_defense = 0.0
        total_uptime = 0.0
        total_service = 0.0
        total_flags = 0
        total_attackers = 0
        total_victims = 0
        total_tick_points = 0.0

        for svc in services:
            sid = svc["id"]
            cur = team_cur.get(sid, {
                "attack_points": 0, "defense_points": 0, "uptime_points": 0,
                "challenge_points": 0, "service_total": 0,
                "flags_captured": 0, "attackers_count": 0, "victims_count": 0,
                "sla_up_count": 0, "sla_total_count": 0,
            })
            prev = team_snap.get(sid, {
                "attack_points": 0, "defense_points": 0, "uptime_points": 0,
                "challenge_points": 0, "service_total": 0,
                "flags_captured": 0, "attackers_count": 0, "victims_count": 0,
                "sla_up_count": 0, "sla_total_count": 0,
            })
            sla_pct_now = _sla_pct(cur["sla_up_count"], cur["sla_total_count"])
            sla_pct_prev = _sla_pct(prev["sla_up_count"], prev["sla_total_count"])
            check_info = checker_statuses.get((team_id, sid)) or {}
            checker_status = check_info.get("status", "OFFLINE")
            put_status, get_status, havoc_status = derive_method_statuses(
                checker_status,
                check_info.get("flag_avail") or {},
                display_tick,
            )
            attack_tick = max(_points(_delta(cur["attack_points"], prev["attack_points"])), 0.0)
            defense_tick = max(_points(_delta(cur["defense_points"], prev["defense_points"])), 0.0)
            uptime_tick = max(_points(_delta(cur["uptime_points"], prev["uptime_points"])), 0.0)
            challenge_tick = _points(attack_tick + defense_tick)
            service_tick = _points(_delta(cur["service_total"], prev["service_total"]))
            service_cells[sid] = {
                "service_name": svc["name"],
                "service_slug": svc.get("slug", svc["name"]),
                "service_display_name": _service_label(svc),
                "service_total": cur["service_total"],
                "service_delta": service_tick,
                "attack_points": cur["attack_points"],
                "attack_delta": attack_tick,
                "defense_points": cur["defense_points"],
                "defense_delta": defense_tick,
                "uptime_points": cur["uptime_points"],
                "uptime_delta": uptime_tick,
                "challenge_points": cur["challenge_points"],
                "challenge_delta": challenge_tick,
                "flags_captured": cur["flags_captured"],
                "flags_delta": _delta(cur["flags_captured"], prev["flags_captured"]),
                "attackers_count": cur["attackers_count"],
                "attackers_delta": _delta(cur["attackers_count"], prev["attackers_count"]),
                "victims_count": cur["victims_count"],
                "victims_delta": _delta(cur["victims_count"], prev["victims_count"]),
                "sla_pct": sla_pct_now,
                "sla_delta": round(sla_pct_now - sla_pct_prev, 2),
                "checker_status": checker_status,
                "is_up": checker_is_up(checker_status),
                "put_status": put_status,
                "get_status": get_status,
                "havoc_status": havoc_status,
            }
            total_attack += cur["attack_points"]
            total_defense += cur["defense_points"]
            total_uptime += cur["uptime_points"]
            total_service += cur["service_total"]
            total_flags += cur["flags_captured"]
            total_attackers += cur["attackers_count"]
            total_victims += cur["victims_count"]
            total_tick_points += service_tick

        rows.append({
            "rank": rank,
            "team_id": team_id,
            "team_name": team["team_name"],
            "nat_alias": team["nat_alias"],
            "country_code": team["country_code"] or "XK",
            "total": _points(team["total"]),
            "total_delta": _points(total_tick_points),
            "service_cells": service_cells,
            "totals": {
                "attack_points": total_attack,
                "defense_points": total_defense,
                "uptime_points": total_uptime,
                "service_total": total_service,
                "flags_captured": total_flags,
                "attackers_count": total_attackers,
                "victims_count": total_victims,
            },
        })

    first_bloods = _service_first_bloods(include_nop=include_nop)
    activity_counts = _service_activity_counts(include_nop=include_nop)
    service_tops = {
        svc["id"]: _service_top_team(
            rows,
            svc["id"],
            first_bloods.get(svc["id"]),
            activity_counts.get(svc["id"]),
        )
        for svc in services
    }

    return {
        "services": services,
        "rows": rows,
        "service_tops": service_tops,
        "display_tick": display_tick,
        "tick_activity": _tick_activity(display_tick, include_nop=include_nop),
        "frozen": freeze_tick is not None,
        "freeze_tick": freeze_tick,
    }


def _status_grid_data(tick_override: Optional[int] = None) -> Dict[str, Any]:
    timing = _scoreboard_timing()
    tick = tick_override if tick_override is not None else (timing["current_round_number"] or None)
    with get_cursor(commit=False) as (_conn, cur):
        cur.execute("SELECT id, name, is_nop FROM teams ORDER BY name ASC;")
        teams = [dict(r) for r in cur.fetchall()]
        cur.execute(
            """
            SELECT id, name, COALESCE(NULLIF(display_name, ''), name) AS display_name
            FROM services
            ORDER BY id ASC;
            """
        )
        services = [dict(r) for r in cur.fetchall()]
        cells: Dict[str, Dict[str, Any]] = {}
        if tick:
            cur.execute(
                """
                SELECT DISTINCT ON (sh.team_id, sh.service_id)
                    sh.team_id, sh.service_id, sh.status, sh.message, sh.flag_avail
                FROM service_health sh
                WHERE sh.tick = %s
                ORDER BY sh.team_id, sh.service_id, sh.checked_at DESC;
                """,
                (tick,),
            )
            for row in cur.fetchall():
                key = f"{row['team_id']}:{row['service_id']}"
                cells[key] = {
                    "status": row["status"],
                    "message": row["message"],
                    "flag_avail": row["flag_avail"],
                }
    return {
        "tick": tick,
        "game_state": timing["timer"].state.value,
        "teams": teams,
        "services": services,
        "cells": cells,
    }


app.include_router(build_debug_router(_status_grid_data))


def _status_grid_html() -> str:
    data = _status_grid_data()
    status_colors = {
        "SUCCESS": "#2f9e44",
        "RECOVERING": "#f08c00",
        "MUMBLE": "#e67700",
        "OFFLINE": "#d6336c",
        "CRASHED": "#862e9c",
    }
    header_cells = "".join(
        f'<th>{html.escape(_service_label(s))}</th>' for s in data["services"]
    )
    body_rows = []
    for team in data["teams"]:
        if team["is_nop"] and os.getenv("STATUS_INCLUDE_NOP", "1") == "0":
            continue
        tname = html.escape(team["name"])
        cells_html = []
        for svc in data["services"]:
            key = f"{team['id']}:{svc['id']}"
            cell = data["cells"].get(key, {})
            status = cell.get("status") or "—"
            message = html.escape((cell.get("message") or "")[:120])
            color = status_colors.get(status, "#6b7280")
            cells_html.append(
                f'<td class="cell" style="--st:{color}">'
                f'<span class="badge">{html.escape(status)}</span>'
                f'<div class="msg">{message}</div></td>'
            )
        body_rows.append(f"<tr><th class=\"team\">{tname}</th>{''.join(cells_html)}</tr>")
    tick_label = data["tick"] if data["tick"] else "—"
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Checker status — KosSim</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 1rem; background: #f4f5f7; }}
  h1 {{ margin: 0 0 0.25rem; }}
  .meta {{ color: #6b7280; margin-bottom: 1rem; }}
  table {{ border-collapse: collapse; width: 100%; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  th, td {{ border: 1px solid #e1e4e8; padding: 0.5rem 0.65rem; vertical-align: top; }}
  th.team {{ text-align: left; background: #eef2f7; }}
  thead th {{ background: #1e6fbf; color: #fff; font-size: 0.85rem; }}
  .badge {{ display: inline-block; font-weight: 700; font-size: 0.75rem; color: var(--st); }}
  .msg {{ font-size: 0.72rem; color: #4b5563; margin-top: 0.25rem; max-width: 14rem; word-break: break-word; }}
  .nav a {{ margin-right: 1rem; }}
</style>
</head><body>
<p class="nav"><a href="/scoreboard">Scoreboard</a> <a href="/public/scoreboard">Public scoreboard</a></p>
<h1>Service status grid</h1>
<p class="meta">Tick <strong>{tick_label}</strong> · Game <strong>{html.escape(data["game_state"])}</strong> · Auto-refresh 5s</p>
<table>
<thead><tr><th>Team</th>{header_cells}</tr></thead>
<tbody>{''.join(body_rows)}</tbody>
</table>
<script>setTimeout(() => location.reload(), 5000);</script>
</body></html>"""


def _scoreboard_html(
    data: Dict[str, Any],
    rotation_seconds: int,
    current_round_number: int,
    next_tick_at: int,
    seconds_to_next_tick: int,
    *,
    title: str = "KosSim Scoreboard",
    game_state: str = "STOPPED",
) -> str:
    updated_at = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    logo_url = html.escape(_scoreboard_logo_url(), quote=True)
    rows = data["rows"]
    services = data["services"]
    service_tops = data["service_tops"]
    leader_name = html.escape(rows[0]["team_name"]) if rows else "-"
    leader_points = f"{rows[0]['total']:g}" if rows else "0"
    teams_count = len(rows)

    def fmt_points(value: float) -> str:
        return f"{value:g}"

    def fmt_delta(value: float, with_arrow: bool = True) -> str:
        if value == 0:
            return ""
        if value > 0:
            sign = "+"
            arrow = " ↑" if with_arrow else ""
            cls = "delta-up"
        else:
            sign = ""
            arrow = " ↓" if with_arrow else ""
            cls = "delta-down"
        text = f"{sign}{value:g}" if abs(value) < 1000 else f"{sign}{int(value)}"
        return f"<span class='{cls}'>{text}{arrow}</span>"

    def render_cell(cell: Dict[str, Any]) -> str:
        sla_pct = cell["sla_pct"]
        sla_class = "sla-up" if sla_pct >= 100 else ("sla-warn" if sla_pct >= 75 else "sla-down")
        badge_label, sla_badge_class = _sla_badge(cell)
        return (
            "<td class='svc-col'><div class='svc-cell'>"
            f"<div class='svc-row'><span class='svc-icon'>🏆</span>"
            f"<span class='svc-val'>{fmt_points(cell['service_total'])}</span>"
            f"{fmt_delta(cell['service_delta'])}</div>"
            f"<div class='svc-row'><span class='svc-icon'>⚔</span>"
            f"<span class='svc-val pos'>+{fmt_points(cell['attack_points'])}</span>"
            f"{fmt_delta(cell['attack_delta'])}</div>"
            f"<div class='svc-row'><span class='svc-icon'>🛡</span>"
            f"<span class='svc-val pos'>+{fmt_points(cell['defense_points'])}</span>"
            f"{fmt_delta(cell['defense_delta'])}</div>"
            f"<div class='svc-row'><span class='svc-icon'>⏱</span>"
            f"<span class='svc-val pos'>+{fmt_points(cell['uptime_points'])}</span>"
            f"{fmt_delta(cell['uptime_delta'])}</div>"
            f"<div class='svc-row'><span class='svc-icon'>★</span>"
            f"<span class='svc-val'>{cell['flags_captured']}</span>"
            f"{fmt_delta(cell['flags_delta'])}</div>"
            f"<div class='svc-row'><span class='svc-icon attackers'>⊙</span>"
            f"<span class='svc-val pos'>+{cell['attackers_count']}</span>"
            f"{fmt_delta(cell['attackers_delta'])}</div>"
            f"<div class='svc-row sla-row'><span class='svc-icon'>🔧</span>"
            f"<span class='svc-val {sla_class}'>{sla_pct:.2f}%</span>"
            f"<span class='sla-badge {sla_badge_class}' title='{html.escape(cell.get('checker_status', ''), quote=True)}'>{badge_label}</span></div>"
            "</div></td>"
        )

    body_rows = []
    for row in rows:
        idx = row["rank"]
        rank_class = f"rank-{idx}" if idx <= 3 else "rank-other"
        flag = _country_flag_emoji(row["country_code"])
        cells_html = "".join(render_cell(row["service_cells"][svc["id"]]) for svc in services)
        team_link = f"/team/{html.escape(row['team_name'], quote=True)}"
        body_rows.append(
            f"<tr class='{rank_class}'>"
            f"<td class='rank-col'><span class='rank-num'>{idx}</span></td>"
            f"<td class='team-col'>"
            f"<a class='team-inner' href='{team_link}'>"
            f"<div class='team-flag'>{flag}</div>"
            f"<div class='team-meta'>"
            f"<div class='team-name'>{html.escape(row['team_name'])}</div>"
            f"<div class='team-nat'>{html.escape(row['nat_alias'])}</div>"
            f"</div>"
            f"</a>"
            f"</td>"
            f"<td class='score-col'>"
            f"<div class='score-big'>{fmt_points(row['total'])}</div>"
            f"<div class='score-delta'>{fmt_delta(row['total_delta'])}</div>"
            f"</td>"
            f"{cells_html}"
            f"</tr>"
        )

    # Top header strip — top team per service
    header_strip = []
    for svc in services:
        top = service_tops.get(svc["id"])
        if not top:
            header_strip.append(f"<th class='svc-head'><div class='svc-head-name'>{html.escape(_service_label(svc))}</div></th>")
            continue
        flag = _country_flag_emoji(top["country_code"])
        first = top.get("first_blood")
        first_html = ""
        if first:
            attacker = html.escape(str(first.get("attacker_team") or ""))
            victim = html.escape(str(first.get("victim_team") or ""))
            target = f" -> {victim}" if victim else ""
            first_html = f"<div class='svc-head-stats first'>★ First blood {attacker}{target}</div>"
        header_strip.append(
            "<th class='svc-head'>"
            f"<div class='svc-head-team'>{flag} <span>{html.escape(top['team_name'])}</span></div>"
            f"<div class='svc-head-stats'>Score {fmt_points(top['service_total'])}</div>"
            f"{first_html}"
            f"<div class='svc-head-stats'>⊙ {top['attackers_count']} Attackers</div>"
            f"<div class='svc-head-stats'>⊘ {top['victims_count']} Victims</div>"
            "</th>"
        )

    service_table_headers = "".join(
        f"<th class='svc-col-head'>🏆 {html.escape(_service_label(svc))} Score</th>" for svc in services
    )

    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg: #f4f5f7;
      --card: #ffffff;
      --line: #e1e4e8;
      --text: #1c1f23;
      --muted: #6b7280;
      --header-bg: #1e6fbf;
      --header-text: #ffffff;
      --rank-1-bg: #fff7c4;
      --rank-1-edge: #f5c518;
      --rank-2-bg: #dde9f7;
      --rank-2-edge: #5fb5ff;
      --rank-3-bg: #ffd9c2;
      --rank-3-edge: #f08a4b;
      --up: #2f9e44;
      --down: #d6336c;
      --accent: #1e6fbf;
      --kos-blue: #244AA5;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: "Inter", "Segoe UI", Tahoma, sans-serif;
      color: var(--text);
      background: var(--bg);
      padding: 0;
      font-size: 13px;
    }}
    .topbar {{
      display: flex;
      align-items: center;
      gap: 16px;
      padding: 12px 18px 8px;
      background: var(--card);
      border-bottom: 1px solid var(--line);
    }}
    .topbar .logo {{
      width: 44px;
      height: 44px;
      border-radius: 50%;
      background: var(--card);
      border: 2px solid var(--line);
      display: grid;
      place-items: center;
      overflow: hidden;
    }}
    .topbar .logo img {{ max-width: 80%; max-height: 80%; object-fit: contain; }}
    .topbar h1 {{ margin: 0; font-size: 18px; font-weight: 700; }}
    .topbar .sub {{ color: var(--muted); font-size: 12px; }}
    .topbar .chips {{ margin-left: auto; display: flex; gap: 8px; align-items: center; }}
    .topbar .chip {{
      border: 1px solid var(--line);
      background: #fafbfc;
      border-radius: 6px;
      font-size: 12px;
      padding: 4px 10px;
      color: var(--text);
    }}
    .topbar .chip strong {{ color: var(--accent); }}
    .progress-wrap {{
      height: 4px;
      background: #e9ecef;
      overflow: hidden;
    }}
    .progress-wrap span {{
      display: block;
      height: 100%;
      width: 0%;
      background: linear-gradient(90deg, var(--accent), #5fb5ff);
      transition: width 0.2s linear;
    }}
    .table-wrap {{ overflow-x: auto; background: var(--card); }}
    table {{ width: 100%; border-collapse: collapse; }}
    thead.svc-top tr th {{
      background: var(--card);
      color: var(--text);
      padding: 10px 8px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
      font-weight: 500;
      text-align: left;
      font-size: 11px;
      min-width: 180px;
    }}
    thead.svc-top th.fixed {{ min-width: 0; }}
    .svc-head-team {{ font-weight: 700; color: var(--down); font-size: 12px; margin-bottom: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .svc-head-stats {{ color: var(--muted); font-size: 11px; line-height: 1.4; }}
    .svc-head-stats.first {{ color: var(--rank-1-edge); font-weight: 800; }}
    thead.col-heads tr th {{
      background: var(--header-bg);
      color: var(--header-text);
      padding: 9px 10px;
      font-size: 12px;
      font-weight: 600;
      text-align: left;
      letter-spacing: 0.02em;
      position: sticky;
      top: 0;
      z-index: 2;
    }}
    thead.col-heads tr th:first-child {{ width: 36px; text-align: center; }}
    thead.col-heads tr th.team-h {{ min-width: 220px; }}
    thead.col-heads tr th.score-h {{ min-width: 140px; }}
    tbody td {{
      border-bottom: 1px solid var(--line);
      padding: 10px 10px;
      vertical-align: top;
      font-variant-numeric: tabular-nums;
    }}
    tbody tr.rank-1 td {{ background: var(--rank-1-bg); }}
    tbody tr.rank-2 td {{ background: var(--rank-2-bg); }}
    tbody tr.rank-3 td {{ background: var(--rank-3-bg); }}
    tbody tr:hover td {{ filter: brightness(0.97); }}
    .rank-col {{ width: 36px; text-align: center; font-weight: 700; font-size: 15px; }}
    .rank-num {{ display: inline-block; }}
    .team-inner {{
      display: flex;
      align-items: center;
      gap: 10px;
      text-decoration: none;
      color: inherit;
    }}
    .team-inner:hover .team-name {{ text-decoration: underline; color: var(--accent); }}
    .team-flag {{
      width: 40px;
      height: 28px;
      display: grid;
      place-items: center;
      font-size: 24px;
      background: linear-gradient(180deg, var(--kos-blue), #1a3a82);
      border: 1px solid #1a3a82;
      border-radius: 3px;
      color: #fff;
      flex-shrink: 0;
      overflow: hidden;
    }}
    .team-name {{ font-weight: 600; font-size: 13px; color: var(--text); }}
    .team-nat {{
      display: inline-block;
      margin-top: 3px;
      padding: 2px 7px;
      border-radius: 4px;
      background: #4dd0c9;
      color: #003a36;
      font-size: 10px;
      font-weight: 600;
      letter-spacing: 0.02em;
    }}
    .score-col {{ width: 130px; min-width: 130px; max-width: 130px; }}
    .rank-col {{ width: 36px; min-width: 36px; max-width: 36px; }}
    .team-col {{ width: 220px; min-width: 220px; max-width: 220px; }}
    .svc-col {{ vertical-align: top; padding: 8px 10px; min-width: 175px; }}
    .score-big {{ font-weight: 700; font-size: 16px; color: var(--text); }}
    .score-delta {{ font-size: 12px; margin-top: 2px; }}
    .svc-cell {{ display: grid; gap: 4px; min-width: 165px; }}
    .svc-row {{
      display: flex;
      align-items: baseline;
      gap: 6px;
      font-size: 12px;
      line-height: 1.25;
      white-space: nowrap;
    }}
    .svc-icon {{
      color: var(--muted);
      text-align: center;
      font-size: 11px;
      width: 14px;
      flex-shrink: 0;
    }}
    .svc-icon.attackers {{ color: var(--up); }}
    .svc-icon.victims {{ color: var(--down); }}
    .svc-val {{ font-weight: 600; }}
    .svc-val.pos {{ color: var(--up); }}
    .svc-val.neg {{ color: var(--down); }}
    .svc-val.sla-up {{ color: var(--up); }}
    .svc-val.sla-warn {{ color: #f59f00; }}
    .svc-val.sla-down {{ color: var(--down); }}
    .delta-up {{ color: var(--up); font-size: 11px; font-weight: 600; }}
    .delta-down {{ color: var(--down); font-size: 11px; font-weight: 600; }}
    .delta-zero {{ color: var(--muted); font-size: 11px; }}
    .svc-row.sla-row .sla-badge {{ margin-left: auto; }}
    .sla-badge {{
      display: inline-flex;
      align-items: center;
      gap: 2px;
      padding: 2px 6px;
      border-radius: 3px;
      font-size: 10px;
      font-weight: 700;
      color: #fff;
    }}
    .sla-badge.badge-up {{ background: var(--up); }}
    .sla-badge.badge-warn {{ background: #f59f00; }}
    .sla-badge.badge-down {{ background: var(--down); }}
    .footer {{ padding: 10px 18px 18px; font-size: 11px; color: var(--muted); background: var(--card); }}
    .toast-wrap {{
      position: fixed;
      top: 18px;
      right: 18px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      z-index: 9999;
      pointer-events: none;
      max-width: 360px;
    }}
    .toast {{
      background: linear-gradient(135deg, #b3001b, #d6336c);
      color: #fff;
      padding: 12px 16px;
      border-radius: 8px;
      box-shadow: 0 6px 16px rgba(0, 0, 0, 0.22);
      font-size: 13px;
      line-height: 1.4;
      animation: toast-in 0.35s ease-out, toast-out 0.4s ease-in 6.4s forwards;
      border: 1px solid rgba(255, 255, 255, 0.25);
    }}
    .toast .toast-title {{
      font-weight: 800;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      font-size: 11px;
      display: flex;
      align-items: center;
      gap: 6px;
      margin-bottom: 4px;
    }}
    .toast .toast-body strong {{ font-weight: 700; }}
    .toast .toast-meta {{
      margin-top: 6px;
      font-size: 11px;
      opacity: 0.85;
    }}
    @keyframes toast-in {{
      from {{ opacity: 0; transform: translateY(-12px) scale(0.96); }}
      to   {{ opacity: 1; transform: translateY(0) scale(1); }}
    }}
    @keyframes toast-out {{
      to {{ opacity: 0; transform: translateX(40px); }}
    }}
    @media (max-width: 900px) {{
      .topbar {{ flex-wrap: wrap; }}
      .topbar .chips {{ margin-left: 0; width: 100%; flex-wrap: wrap; }}
    }}
  </style>
</head>
<body>
  <div class="progress-wrap"><span id="tick-progress-fill"></span></div>
  <header class="topbar">
    <div class="logo">
      <img src="{logo_url}" alt="logo" onerror="this.style.display='none';">
    </div>
    <div>
      <h1>{html.escape(title)}</h1>
      <div class="sub">Kosova Cyber Team Attack/Defense — Updated {updated_at}</div>
    </div>
    <div class="chips">
      <span class="chip">Round <strong id="tick-round">{current_round_number}</strong></span>
      <span class="chip">Game <strong>{_esc(game_state)}</strong></span>
      <span class="chip">Next tick <strong id="tick-countdown">{seconds_to_next_tick if seconds_to_next_tick > 0 else "—"}</strong><span id="tick-countdown-suffix">{"s" if seconds_to_next_tick > 0 else ""}</span></span>
      <span class="chip">Leader <strong>{leader_name}</strong> · {leader_points}</span>
      <span class="chip">{teams_count} teams</span>
    </div>
  </header>
  <div class="table-wrap">
    <table>
      <thead class="svc-top">
        <tr>
          <th class="fixed"></th>
          <th class="fixed"></th>
          <th class="fixed"></th>
          {''.join(header_strip)}
        </tr>
      </thead>
      <thead class="col-heads">
        <tr>
          <th>#</th>
          <th class="team-h">🏳️ Team</th>
          <th class="score-h">🏆 Score</th>
          {service_table_headers}
        </tr>
      </thead>
      <tbody>
        {''.join(body_rows)}
      </tbody>
    </table>
  </div>
  <div class="footer">Attack-defense scoring: service score is attack plus defense, and the final service total is service score multiplied by SLA.</div>
  <div class="toast-wrap" id="toasts" aria-live="polite"></div>
  <script>
    (() => {{
      const rotationSeconds = Math.max(1, {rotation_seconds});
      let nextTickAt = {next_tick_at};
      const gameRunning = {str(game_state == "RUNNING").lower()};
      const knownRound = {current_round_number};
      let reloading = false;
      let lastRemaining = Math.max(0, {seconds_to_next_tick});
      const countdownEl = document.getElementById("tick-countdown");
      const countdownSuffix = document.getElementById("tick-countdown-suffix");
      const roundEl = document.getElementById("tick-round");
      const progressEl = document.getElementById("tick-progress-fill");

      const tick = () => {{
        const now = Date.now() / 1000;
        const remaining = nextTickAt > now ? Math.max(0, Math.ceil(nextTickAt - now)) : 0;
        const elapsed = nextTickAt > now
          ? Math.max(0, rotationSeconds - remaining)
          : rotationSeconds;
        const pct = Math.max(0, Math.min(100, (elapsed / rotationSeconds) * 100));

        roundEl.textContent = String(knownRound);
        if (remaining > 0) {{
          countdownEl.textContent = String(remaining);
          countdownSuffix.textContent = "s";
        }} else {{
          countdownEl.textContent = gameRunning ? "…" : "—";
          countdownSuffix.textContent = "";
        }}
        progressEl.style.width = `${{pct.toFixed(2)}}%`;

        // Reload once when the countdown crosses zero (not every 250ms while stuck at 0).
        if (gameRunning && lastRemaining > 0 && remaining <= 0 && !reloading) {{
          reloading = true;
          window.location.reload();
        }}
        lastRemaining = remaining;
      }};

      tick();
      setInterval(tick, 250);

      const nowSec = Date.now() / 1000;
      const refreshDelayMs = Math.max(500, (nextTickAt - nowSec) * 1000 + 300);
      if (gameRunning && nextTickAt > nowSec) {{
        setTimeout(() => {{
          if (!reloading) {{
            reloading = true;
            window.location.reload();
          }}
        }}, refreshDelayMs);
      }} else if (gameRunning && nextTickAt <= nowSec) {{
        // Rotator may be catching up after a late tick; poll without full reload storm.
        const waitForRound = async () => {{
          try {{
            const r = await fetch("/api/v1/current_round");
            if (!r.ok) return;
            const d = await r.json();
            if ((d.round || 0) > knownRound) {{
              window.location.reload();
            }}
          }} catch (e) {{}}
        }};
        setInterval(waitForRound, 5000);
      }}

      // First-blood toast feed
      const toastWrap = document.getElementById("toasts");
      const seen = new Set();
      const storageKey = "kossim-firstblood-since";
      let since = parseFloat(sessionStorage.getItem(storageKey) || "0") || 0;
      // Seed `seen` with whatever the API already has so we don't replay
      // history each page load.
      const flagEmoji = (cc) => {{
        if (!cc || cc.length !== 2) return "🏳";
        const A = 0x1F1E6, base = "A".charCodeAt(0);
        return String.fromCodePoint(A + cc.charCodeAt(0) - base) +
               String.fromCodePoint(A + cc.charCodeAt(1) - base);
      }};
      const renderToast = (ev) => {{
        const el = document.createElement("div");
        el.className = "toast";
        const attacker = `${{flagEmoji(ev.submitter_country)}} ${{ev.submitter_team}}`;
        const target = `${{flagEmoji(ev.target_country)}} ${{ev.target_team || "?"}}`;
        el.innerHTML = (
          '<div class="toast-title">🩸 FIRST BLOOD · ' + (ev.service_display_name || ev.service || "") + '</div>' +
          '<div class="toast-body"><strong>' + attacker + '</strong> drew first blood on <strong>' + target + '</strong></div>' +
          '<div class="toast-meta">tick ' + (ev.tick_issued || "-") + ' · payload ' + (ev.payload ?? "-") + '</div>'
        );
        toastWrap.appendChild(el);
        setTimeout(() => el.remove(), 7400);
      }};
      const seedSeen = async () => {{
        try {{
          const r = await fetch("/api/v1/firstbloods?limit=100");
          if (!r.ok) return;
          const data = await r.json();
          for (const ev of (data.events || [])) {{
            seen.add(ev.id);
            if (ev.timestamp && ev.timestamp > since) since = ev.timestamp;
          }}
        }} catch (e) {{}}
      }};
      const pollFirstBloods = async () => {{
        try {{
          const url = "/api/v1/firstbloods?limit=20" + (since ? "&since=" + since : "");
          const r = await fetch(url);
          if (!r.ok) return;
          const data = await r.json();
          const events = (data.events || []).slice().sort(
            (a, b) => (a.timestamp || 0) - (b.timestamp || 0)
          );
          for (const ev of events) {{
            if (seen.has(ev.id)) continue;
            seen.add(ev.id);
            renderToast(ev);
            if (ev.timestamp && ev.timestamp > since) since = ev.timestamp;
          }}
          sessionStorage.setItem(storageKey, String(since));
        }} catch (e) {{}}
      }};
      seedSeen();
      setInterval(pollFirstBloods, 3000);
    }})();
  </script>
</body>
</html>
"""


@app.on_event("startup")
def _startup() -> None:
    if os.getenv("AUTOINIT_DB", "1") != "0":
        bootstrap_database()
    bootstrap_patches_table()
    bootstrap_wiki_table()
    start_tcp_server_background()


@app.get("/")
def root() -> Dict[str, str]:
    return {"service": "kossim-control", "status": "ok"}


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "healthy"}


@app.get("/metrics")
def metrics(
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> Response:
    _require_internal(request, authorization)
    with get_cursor(commit=False) as (_conn, cur):
        data = build_observability(cur, ticks=120)
    return Response(render_prometheus_metrics(data), media_type="text/plain; version=0.0.4")


@app.get("/api/v1/network/router-bundle")
def router_bundle(
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> StreamingResponse:
    _require_internal(request, authorization)
    with get_cursor(commit=True) as (_conn, cur):
        settings, plans = load_network_plans(cur)
    files = build_router_bundle(settings, plans)
    buf = BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(files):
            zf.writestr(name, files[name])
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="kossim-router-bundle.zip"'},
    )


@app.post("/api/v1/vulnboxes/{vulnbox_id}/status")
def report_vulnbox_status(
    vulnbox_id: int,
    request: Request,
    authorization: Optional[str] = Header(default=None),
    body: Dict[str, Any] = Body(...),
) -> Dict[str, bool]:
    _require_internal(request, authorization)
    status = str(body.get("status") or "UNKNOWN").upper()[:32]
    message = str(body.get("message") or "")[:2000]
    with get_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """
            UPDATE vulnboxes
            SET observed_status = %s, last_report_at = NOW(), updated_at = NOW()
            WHERE id = %s
            RETURNING team_id;
            """,
            (status, vulnbox_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="vulnbox not found")
        record_vulnbox_event(
            cur,
            vulnbox_id=vulnbox_id,
            team_id=int(row["team_id"]),
            action="status",
            status=status,
            message=message,
        )
    return {"ok": True}


def _team_page_html(detail: Dict[str, Any]) -> str:
    team = detail["team"]
    services = detail["services"]
    history = detail["checker_history"]
    submissions = detail["recent_submissions"]
    captures = detail["recent_captures_from"]

    flag = _country_flag_emoji(team["country_code"])
    team_name = html.escape(team["name"])
    nat_alias = html.escape(team["nat_alias"] or "")
    total = f"{team['total']:g}"
    updated_at = team["updated_at"] or "-"

    def fmt(value: float) -> str:
        return f"{value:g}"

    service_rows = "".join(
        f"<tr>"
        f"<td>{html.escape(s['service_name'])}</td>"
        f"<td class='pos'>{fmt(s['off_points'])}</td>"
        f"<td class='pos'>{fmt(s['def_points'])}</td>"
        f"<td>{fmt(s['sla_points'])}</td>"
        f"<td>+{fmt(s['sla_delta'])}</td>"
        f"<td>{s['flag_captured_count']}</td>"
        f"<td>{s['flag_stolen_count']}</td>"
        f"<td>tick {s['latest_tick'] or '-'}</td>"
        f"</tr>"
        for s in services
    )

    status_class = {
        "SUCCESS": "ok",
        "RECOVERING": "warn",
        "MUMBLE": "warn",
        "FLAGMISSING": "warn",
        "OFFLINE": "bad",
        "TIMEOUT": "bad",
        "CRASHED": "bad",
    }
    history_rows = "".join(
        f"<tr>"
        f"<td>{h['tick']}</td>"
        f"<td>{html.escape(h['service'])}</td>"
        f"<td class='{status_class.get(h['status'], '')}'>{html.escape(h['status'])}</td>"
        f"<td class='dim small'>{html.escape((h['checked_at'] or '')[11:19])}</td>"
        f"</tr>"
        for h in history[:24]
    )

    sub_rows = "".join(
        f"<tr>"
        f"<td class='dim small'>{html.escape((dt.datetime.utcfromtimestamp(s['timestamp']).isoformat() + 'Z') if s['timestamp'] else '')}</td>"
        f"<td>{html.escape(s['target_team'] or '-')}</td>"
        f"<td>{html.escape(s['service'] or '-')}</td>"
        f"<td>{s['tick_issued'] or '-'}/{s['payload'] if s['payload'] is not None else '-'}</td>"
        f"<td class='{'ok' if s['result']=='accepted' else 'dim'}'>{html.escape(s['result'])}{' 🩸' if s['is_firstblood'] else ''}</td>"
        f"<td class='pos'>+{s['points_awarded']}</td>"
        f"</tr>"
        for s in submissions[:25]
    )

    cap_rows = "".join(
        f"<tr>"
        f"<td class='dim small'>{html.escape((dt.datetime.utcfromtimestamp(s['timestamp']).isoformat() + 'Z') if s['timestamp'] else '')}</td>"
        f"<td>{html.escape(s['attacker'])}</td>"
        f"<td>{html.escape(s['service'] or '-')}</td>"
        f"<td>{s['tick_issued'] or '-'}/{s['payload'] if s['payload'] is not None else '-'}</td>"
        f"<td class='bad'>{'🩸 first blood' if s['is_firstblood'] else 'captured'}</td>"
        f"</tr>"
        for s in captures[:25]
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{team_name} — KosSim</title>
<style>
  :root {{
    --bg:#f4f5f7; --card:#fff; --line:#e1e4e8; --text:#1c1f23; --muted:#6b7280;
    --ok:#2f9e44; --warn:#f59f00; --bad:#d6336c; --accent:#1e6fbf;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family:"Inter","Segoe UI",sans-serif; background:var(--bg); color:var(--text); font-size:13px; }}
  header {{ background:var(--card); border-bottom:1px solid var(--line); padding:16px 22px; display:flex; gap:14px; align-items:center; }}
  header .flag {{ font-size:36px; }}
  header h1 {{ margin:0; font-size:20px; }}
  header .nat {{ background:#4dd0c9; color:#003a36; padding:2px 8px; border-radius:4px; font-size:10px; font-weight:600; }}
  header .total {{ margin-left:auto; text-align:right; }}
  header .total .num {{ font-size:26px; font-weight:700; color:var(--accent); }}
  header .total .lbl {{ color:var(--muted); font-size:11px; }}
  main {{ padding:18px 22px; display:grid; gap:18px; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); }}
  section {{ background:var(--card); border:1px solid var(--line); border-radius:6px; padding:14px 16px; }}
  section h2 {{ margin:0 0 10px; font-size:14px; text-transform:uppercase; letter-spacing:0.04em; color:var(--muted); }}
  table {{ width:100%; border-collapse:collapse; font-variant-numeric:tabular-nums; }}
  th, td {{ padding:6px 8px; text-align:left; border-bottom:1px solid var(--line); }}
  th {{ font-size:11px; text-transform:uppercase; color:var(--muted); font-weight:600; }}
  .ok {{ color:var(--ok); font-weight:600; }}
  .warn {{ color:var(--warn); font-weight:600; }}
  .bad {{ color:var(--bad); font-weight:600; }}
  .pos {{ color:var(--ok); font-weight:600; }}
  .dim {{ color:var(--muted); }}
  .small {{ font-size:11px; }}
  .summary {{ display:grid; grid-template-columns: repeat(3, 1fr); gap:12px; }}
  .summary .card {{ background:#fafbfc; border:1px solid var(--line); border-radius:4px; padding:10px 12px; }}
  .summary .card .lbl {{ color:var(--muted); font-size:11px; text-transform:uppercase; }}
  .summary .card .num {{ font-size:17px; font-weight:700; margin-top:2px; }}
  a {{ color:var(--accent); text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  .back {{ font-size:12px; }}
  footer {{ padding:14px 22px; color:var(--muted); font-size:11px; }}
</style>
</head><body>
<header>
  <span class="flag">{flag}</span>
  <div>
    <h1>{team_name}</h1>
    <div class="dim small"><span class="nat">{nat_alias}</span> · updated {html.escape(updated_at)}</div>
  </div>
  <div class="total">
    <div class="num">{total}</div>
    <div class="lbl">total points</div>
    <div class="back"><a href="/scoreboard">← back to scoreboard</a></div>
  </div>
</header>
<main>
  <section>
    <h2>Score breakdown</h2>
    <div class="summary">
      <div class="card"><div class="lbl">⚔ Attack</div><div class="num pos">{fmt(team['attack_points'])}</div></div>
      <div class="card"><div class="lbl">🛡 Defense</div><div class="num pos">{fmt(team['defense_points'])}</div></div>
      <div class="card"><div class="lbl">⏱ SLA</div><div class="num">{fmt(team['uptime_points'])}</div></div>
    </div>
  </section>
  <section>
    <h2>Per-service performance</h2>
    <table>
      <thead><tr><th>Service</th><th>⚔ Off</th><th>🛡 Def</th><th>⏱ SLA</th><th>ΔSLA</th><th>★ Captured</th><th>⊘ Lost</th><th>Tick</th></tr></thead>
      <tbody>{service_rows}</tbody>
    </table>
  </section>
  <section>
    <h2>Checker history (recent)</h2>
    <table>
      <thead><tr><th>Tick</th><th>Service</th><th>Status</th><th>Checked</th></tr></thead>
      <tbody>{history_rows}</tbody>
    </table>
  </section>
  <section>
    <h2>Recent flag submissions</h2>
    <table>
      <thead><tr><th>When</th><th>Target</th><th>Service</th><th>Tick/Payload</th><th>Result</th><th>+pts</th></tr></thead>
      <tbody>{sub_rows or '<tr><td colspan=6 class=dim>No submissions yet</td></tr>'}</tbody>
    </table>
  </section>
  <section>
    <h2>Flags lost to other teams</h2>
    <table>
      <thead><tr><th>When</th><th>Attacker</th><th>Service</th><th>Tick/Payload</th><th>Tag</th></tr></thead>
      <tbody>{cap_rows or '<tr><td colspan=5 class=dim>Nobody has captured a flag from this team (yet)</td></tr>'}</tbody>
    </table>
  </section>
</main>
<footer>KosSim per-team view. Refresh to update.</footer>
</body></html>"""


def _scoreboard_timing() -> Dict[str, Any]:
    with get_cursor(commit=True) as (_conn, cur):
        timer = load_timer(cur)
        timer.sync_scheduled_start(cur)
        timer.load(cur)
    rotation = _rotation_seconds()
    now_ts = time.time()
    current_round_number = timer.current_tick if timer.current_tick >= 1 else 0
    next_tick_at = timer.tick_end or int(now_ts + rotation)
    seconds_to_next_tick = max(0, int(next_tick_at - now_ts)) if timer.tick_end else 0
    return {
        "timer": timer,
        "rotation": rotation,
        "current_round_number": current_round_number,
        "next_tick_at": next_tick_at,
        "seconds_to_next_tick": seconds_to_next_tick,
    }


app.include_router(
    build_scoreboard_router(
        scoreboard_timing=_scoreboard_timing,
        build_scoreboard_data=_build_scoreboard_data,
        max_accepted_per_round=_max_accepted_per_round,
        request_is_internal=_request_is_internal,
    )
)
app.include_router(
    build_team_router(
        points=_points,
        effective_freeze_tick=_effective_freeze_tick,
        request_is_internal=_request_is_internal,
        require_internal=_require_internal,
    )
)


mount_spa(app)
