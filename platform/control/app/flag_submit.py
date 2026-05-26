"""Shared flag submission logic for HTTP and TCP submitters."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from .db import get_cursor
from .event_log import LogLevel, write_log
from .flag_crypto import decode_flag, flag_regex_pattern
from .game_timer import CTFState, GameTimer


def _submission_points() -> int:
    return int(os.getenv("SUBMISSION_POINTS", "1"))


def _retention_ticks() -> int:
    return max(1, int(os.getenv("FLAG_RETENTION_TICKS", "5")))


def _max_accepted_per_round() -> int:
    return int(os.getenv("MAX_ACCEPTED_PER_TEAM_PER_ROUND", "0"))


def _current_round_id(now: Optional[float] = None) -> int:
    import time

    rotation = int(os.getenv("ROTATION_SECONDS", "120"))
    ts = now if now is not None else time.time()
    return int(ts // rotation)


def _current_tick(cur: Any) -> int:
    timer = GameTimer()
    timer.load(cur)
    if timer.current_tick >= 1:
        return timer.current_tick
    cur.execute("SELECT COALESCE(MAX(tick), 0) AS max_tick FROM flag_rounds;")
    return int(cur.fetchone()["max_tick"]) + 1


def _game_running(cur: Any) -> bool:
    timer = GameTimer()
    timer.load(cur)
    return timer.state == CTFState.RUNNING


TCP_STATUS_LINES: Dict[str, str] = {
    "accepted": "[OK]\n",
    "duplicate": "[ERR] Already submitted\n",
    "expired": "[ERR] Expired\n",
    "own_flag": "[ERR] This is your own flag\n",
    "invalid": "[ERR] Invalid flag\n",
    "nop_target": "[ERR] Can't submit flag from NOP team\n",
    "future_flag": "[ERR] Invalid flag (future)\n",
    "round_limit": "[ERR] Round limit\n",
    "offline": "[OFFLINE] CTF not running\n",
    "bad_length": "[ERR] Wrong length\n",
    "bad_format": "[ERR] Invalid flag (wrong format)\n",
    "bad_ip": "[ERR] Invalid source IP\n",
    "nop_submitter": "[ERR] Can't submit flag as NOP team\n",
}


def tcp_line_for_status(status: str) -> str:
    return TCP_STATUS_LINES.get(status, "[ERR] Invalid flag\n")


def _serialize_submitter(cur: Any, submitter_id: int) -> None:
    """Hold a per-team advisory lock for the rest of the transaction.

    Prevents two concurrent batches from the same team from each reading
    the round-limit counter before the other commits, which would let a
    team double its effective cap.
    """
    cur.execute("SELECT pg_advisory_xact_lock(%s);", (int(submitter_id),))


def _resolve_firstblood(cur: Any, target_team_id: int, service_id: int) -> bool:
    """Return whether this submission should be marked as firstblood.

    Uses a non-blocking advisory lock on ``(target_team_id, service_id)``
    so concurrent submitters racing for the same firstblood slot can't
    both observe an empty prior-acceptance set and both stamp firstblood.
    The submitter who acquires the lock does the SQL check; the loser
    conservatively returns ``False`` (their submission still counts,
    just without the firstblood marker).
    """
    cur.execute(
        "SELECT pg_try_advisory_xact_lock(%s, %s) AS got;",
        (int(target_team_id), int(service_id)),
    )
    row = cur.fetchone()
    got = bool(row["got"]) if row else False
    if not got:
        return False
    cur.execute(
        """
        SELECT 1
        FROM submissions
        WHERE result = 'accepted'
          AND target_team_id = %s
          AND service_id = %s
        LIMIT 1;
        """,
        (int(target_team_id), int(service_id)),
    )
    return cur.fetchone() is None


def submit_flags(
    *,
    submitter_team_id: int,
    flags: List[str],
    source_ip: str,
    require_running: bool = True,
) -> Dict[str, Any]:
    points_per_flag = _submission_points()
    retention = _retention_ticks()
    max_per_round = _max_accepted_per_round()

    with get_cursor(commit=True) as (_conn, cur):
        if require_running and not _game_running(cur):
            return {
                "offline": True,
                "results": [
                    {"flag": f, "status": "offline", "tcp_line": TCP_STATUS_LINES["offline"]}
                    for f in flags
                    if f.strip()
                ],
            }

        cur.execute("SELECT id, name, is_nop FROM teams WHERE id = %s;", (submitter_team_id,))
        submitter = cur.fetchone()
        if not submitter:
            raise ValueError("invalid submitter")
        if submitter["is_nop"]:
            raise ValueError("nop submitter")

        submitter_id = int(submitter["id"])
        submitter_name = submitter["name"]

        _serialize_submitter(cur, submitter_id)

        tick_now = _current_tick(cur)
        current_round_id = tick_now if tick_now >= 1 else _current_round_id()
        oldest_acceptable_tick = max(1, tick_now - retention + 1)

        cur.execute("SELECT id, name, is_nop FROM teams;")
        team_meta: Dict[int, Dict[str, Any]] = {int(r["id"]): dict(r) for r in cur.fetchall()}
        cur.execute("SELECT id, name FROM services;")
        service_meta: Dict[int, str] = {int(r["id"]): r["name"] for r in cur.fetchall()}

        cur.execute(
            """
            SELECT COUNT(1) AS count
            FROM submissions
            WHERE submitter_team_id = %s
              AND round_id = %s
              AND result = 'accepted';
            """,
            (submitter_id, current_round_id),
        )
        accepted_this_round = int(cur.fetchone()["count"])

        accepted_count = 0
        total_points = 0
        result_rows: List[Dict[str, Any]] = []

        for raw_flag in flags:
            flag = raw_flag.strip()
            if not flag:
                continue

            cur.execute(
                """
                SELECT id, result, is_firstblood
                FROM submissions
                WHERE submitter_team_id = %s AND flag = %s;
                """,
                (submitter_id, flag),
            )
            duplicate = cur.fetchone()
            if duplicate:
                cur.execute(
                    """
                    INSERT INTO submissions (
                        submitter_team_id, target_team_id, service_id, round_id,
                        tick_issued, payload, flag, result, points_awarded, source_ip
                    )
                    VALUES (%s, NULL, NULL, %s, NULL, NULL, %s, 'duplicate', 0, %s)
                    ON CONFLICT (submitter_team_id, flag) DO NOTHING;
                    """,
                    (submitter_id, current_round_id, flag, source_ip),
                )
                result_rows.append(_result_row(flag, "duplicate", None, None, 0, False))
                continue

            info = decode_flag(flag)
            if info is None:
                cur.execute(
                    """
                    INSERT INTO submissions (
                        submitter_team_id, target_team_id, service_id, round_id,
                        tick_issued, payload, flag, result, points_awarded, source_ip
                    )
                    VALUES (%s, NULL, NULL, %s, NULL, NULL, %s, 'invalid', 0, %s);
                    """,
                    (submitter_id, current_round_id, flag, source_ip),
                )
                result_rows.append(_result_row(flag, "invalid", None, None, 0, False))
                continue

            target_team = team_meta.get(info.team_id)
            service_name = service_meta.get(info.service_id)

            status = "accepted"
            points_awarded = 0
            is_first_blood = False

            if target_team is None or service_name is None:
                status = "invalid"
            elif info.team_id == submitter_id:
                status = "own_flag"
            elif target_team.get("is_nop"):
                status = "nop_target"
            elif info.tick < oldest_acceptable_tick:
                status = "expired"
            elif info.tick > tick_now:
                status = "future_flag"
            elif max_per_round > 0 and accepted_this_round >= max_per_round:
                status = "round_limit"
            else:
                status = "accepted"
                points_awarded = points_per_flag
                is_first_blood = _resolve_firstblood(
                    cur, info.team_id, info.service_id
                )

            cur.execute("SELECT round_id FROM flag_rounds WHERE tick = %s;", (info.tick,))
            row = cur.fetchone()
            flag_round_id = int(row["round_id"]) if row else None

            cur.execute(
                """
                INSERT INTO submissions (
                    submitter_team_id, target_team_id, service_id, round_id,
                    tick_issued, payload, flag, result, points_awarded,
                    is_firstblood, source_ip
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                """,
                (
                    submitter_id,
                    info.team_id if target_team is not None else None,
                    info.service_id if service_name is not None else None,
                    flag_round_id,
                    info.tick,
                    info.payload,
                    flag,
                    status,
                    points_awarded,
                    is_first_blood,
                    source_ip,
                ),
            )

            if status == "accepted":
                accepted_count += 1
                accepted_this_round += 1
                total_points += points_awarded
                tgt = target_team["name"] if target_team else "?"
                svc = service_name or "?"
                if is_first_blood:
                    write_log(
                        "submit",
                        f"First blood: {submitter_name} → {tgt} ({svc})",
                        f"tick={info.tick} payload={info.payload}",
                        LogLevel.NOTIFICATION,
                        cur=cur,
                    )
                else:
                    write_log(
                        "submit",
                        f"Flag accepted: {submitter_name} → {tgt} ({svc})",
                        f"tick={info.tick}",
                        LogLevel.INFO,
                        cur=cur,
                    )

            result_rows.append(
                _result_row(
                    flag,
                    status,
                    target_team["name"] if target_team is not None else None,
                    service_name,
                    points_awarded,
                    is_first_blood,
                    tick_issued=info.tick,
                    payload=info.payload,
                )
            )

        return {
            "offline": False,
            "submitter_team": submitter_name,
            "source_ip": source_ip,
            "round_id": current_round_id,
            "tick": tick_now,
            "retention_ticks": retention,
            "max_accepted_per_team_per_round": max_per_round,
            "accepted_this_round_after_submit": accepted_this_round,
            "accepted_count": accepted_count,
            "total_points_awarded": total_points,
            "flag_regex": flag_regex_pattern(),
            "results": result_rows,
        }


def _result_row(
    flag: str,
    status: str,
    target_team: Optional[str],
    service: Optional[str],
    points: int,
    is_firstblood: bool,
    *,
    tick_issued: Optional[int] = None,
    payload: Optional[int] = None,
) -> Dict[str, Any]:
    return {
        "flag": flag,
        "status": status,
        "tcp_line": tcp_line_for_status(status),
        "target_team": target_team,
        "service": service,
        "tick_issued": tick_issued,
        "payload": payload,
        "points_awarded": points,
        "is_firstblood": is_firstblood,
    }


def resolve_submitter_by_ip(cur: Any, ip: str) -> Optional[int]:
    """Map client IP to team id via TEAM_SUBMIT_IP_MAP (name=ip,...)."""
    from .init_db import _parse_map

    mapping = _parse_map(os.getenv("TEAM_SUBMIT_IP_MAP", ""))
    if not mapping:
        return None
    # Allow team1=1.2.3.4 or 1.2.3.4=team1
    for key, value in mapping.items():
        if value == ip:
            cur.execute("SELECT id FROM teams WHERE name = %s AND is_nop = FALSE;", (key,))
            row = cur.fetchone()
            return int(row["id"]) if row else None
        if key == ip:
            cur.execute("SELECT id FROM teams WHERE name = %s AND is_nop = FALSE;", (value,))
            row = cur.fetchone()
            return int(row["id"]) if row else None
    return None


def resolve_submitter_by_token(cur: Any, token: str) -> Optional[int]:
    cur.execute(
        "SELECT id FROM teams WHERE submit_token = %s AND is_nop = FALSE;",
        (token.strip(),),
    )
    row = cur.fetchone()
    return int(row["id"]) if row else None
