"""KosSim rotator: tick clock + Eno-protocol checker driver + A/D scoring.

On every tick boundary the rotator does three things, in order:

  1. Allocate the new flag-round (sequential ``tick`` is the source of truth
     for everything downstream; raw ``round_id`` is just ``time.time() //
     ROTATION_SECONDS``).
  2. Score the previous tick using the A/D formula -- this needs the
     checker results from the just-closed tick (already in ``service_health``)
     and any submissions teams made during it.
  3. Run checkers against every (team, service) for the new tick: PUTFLAG for
     all flag variants, GETFLAG for the current tick and every retention-window
     tick. Status, flag-availability and attack-info are persisted into
     ``service_health`` and ``flags``.

The rotator is the only writer for ``team_tick_points`` and ``score_snapshots``.
``scores`` (the latest summary view used by the scoreboard) is recomputed
from the latest ``team_tick_points`` row per (team, service).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from .db import get_cursor
from .eno_checker import is_active
from .event_log import LogLevel, write_log
from .game_timer import CTFState, load_timer, rotation_seconds
from .init_db import bootstrap_database
from .checker_jobs import (
    checker_tick_ready,
    finalize_overdue_checker_jobs,
    log_checker_tick_summary,
    schedule_checker_jobs,
)
from .scoring import (
    ServiceSpec,
    StolenFlag,
    TeamPointsLite,
    calculate_scoring_for_tick,
)


def _rotation_seconds() -> int:
    return int(os.getenv("ROTATION_SECONDS", "120"))


def _retention_ticks() -> int:
    return max(1, int(os.getenv("FLAG_RETENTION_TICKS", "5")))


# -----------------------------------------------------------------------------
# Tick + flag_round helpers
# -----------------------------------------------------------------------------


def _ensure_flag_round(cur: Any, round_id: int, starts_at: dt.datetime, ends_at: dt.datetime) -> int:
    """Ensure a flag_rounds row exists for ``round_id`` and return its tick."""
    cur.execute("SELECT tick FROM flag_rounds WHERE round_id = %s;", (round_id,))
    row = cur.fetchone()
    if row is not None and row["tick"] is not None:
        return int(row["tick"])

    cur.execute("SELECT COALESCE(MAX(tick), 0) AS max_tick FROM flag_rounds;")
    next_tick = int(cur.fetchone()["max_tick"]) + 1
    cur.execute(
        """
        INSERT INTO flag_rounds (round_id, starts_at, ends_at, rotation_seconds, tick)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (round_id) DO UPDATE
        SET tick = COALESCE(flag_rounds.tick, EXCLUDED.tick);
        """,
        (round_id, starts_at, ends_at, _rotation_seconds(), next_tick),
    )
    cur.execute("SELECT tick FROM flag_rounds WHERE round_id = %s;", (round_id,))
    return int(cur.fetchone()["tick"])


def _round_id_for_tick(cur: Any, tick: int) -> Optional[int]:
    cur.execute("SELECT round_id FROM flag_rounds WHERE tick = %s;", (tick,))
    row = cur.fetchone()
    return None if row is None else int(row["round_id"])


def _load_services(cur: Any) -> List[ServiceSpec]:
    cur.execute(
        "SELECT id, name, num_payloads, flags_per_tick FROM services ORDER BY id;"
    )
    return [
        ServiceSpec(
            id=int(r["id"]),
            name=r["name"],
            num_payloads=int(r["num_payloads"] or 1),
            flags_per_tick=int(r["flags_per_tick"] or 1),
        )
        for r in cur.fetchall()
    ]


def _load_team_ids(cur: Any) -> Tuple[List[int], Optional[int]]:
    cur.execute("SELECT id, is_nop FROM teams ORDER BY id;")
    team_ids: List[int] = []
    nop_id: Optional[int] = None
    for row in cur.fetchall():
        tid = int(row["id"])
        team_ids.append(tid)
        if row["is_nop"]:
            nop_id = tid
    return team_ids, nop_id


# -----------------------------------------------------------------------------
# Score persistence
# -----------------------------------------------------------------------------


def _load_last_tick_points(
    cur: Any, prior_tick: int
) -> Dict[Tuple[int, int], TeamPointsLite]:
    if prior_tick < 1:
        return {}
    cur.execute(
        """
        SELECT team_id, service_id, off_points, def_points, sla_points, sla_delta,
               flag_captured_count, flag_stolen_count
        FROM team_tick_points
        WHERE tick = %s;
        """,
        (prior_tick,),
    )
    out: Dict[Tuple[int, int], TeamPointsLite] = {}
    for row in cur.fetchall():
        out[(int(row["team_id"]), int(row["service_id"]))] = TeamPointsLite(
            team_id=int(row["team_id"]),
            service_id=int(row["service_id"]),
            tick=prior_tick,
            off_points=float(row["off_points"]),
            def_points=float(row["def_points"]),
            sla_points=float(row["sla_points"]),
            sla_delta=float(row["sla_delta"]),
            flag_captured_count=int(row["flag_captured_count"]),
            flag_stolen_count=int(row["flag_stolen_count"]),
        )
    return out


def _load_checker_results(
    cur: Any, ticks: List[int]
) -> Dict[int, Dict[Tuple[int, int], Tuple[str, Optional[Dict[str, str]]]]]:
    if not ticks:
        return {}
    cur.execute(
        """
        SELECT tick, team_id, service_id, status, flag_avail
        FROM service_health
        WHERE tick = ANY(%s);
        """,
        (ticks,),
    )
    out: Dict[int, Dict[Tuple[int, int], Tuple[str, Optional[Dict[str, str]]]]] = {}
    for row in cur.fetchall():
        flag_avail_raw = row["flag_avail"]
        if isinstance(flag_avail_raw, str):
            try:
                flag_avail = json.loads(flag_avail_raw)
            except Exception:
                flag_avail = None
        else:
            flag_avail = flag_avail_raw  # psycopg2 already json-decoded JSONB
        out.setdefault(int(row["tick"]), {})[
            (int(row["team_id"]), int(row["service_id"]))
        ] = (str(row["status"]), flag_avail)
    return out


def _load_num_active(
    cur: Any, ticks: List[int]
) -> Dict[int, Set[int]]:
    if not ticks:
        return {}
    cur.execute(
        """
        SELECT tick, team_id, status
        FROM service_health
        WHERE tick = ANY(%s);
        """,
        (ticks,),
    )
    out: Dict[int, Set[int]] = defaultdict(set)
    for row in cur.fetchall():
        if is_active(str(row["status"])):
            out[int(row["tick"])].add(int(row["team_id"]))
    return dict(out)


def _load_prev_attacking(
    cur: Any, current_tick: int, retention: int
) -> Dict[Tuple[int, int, int], Dict[int, Set[int]]]:
    """Build the (tick_issued, service_id, payload) -> attacker -> {victims}
    map from accepted submissions that arrived in earlier ticks."""
    if current_tick <= 1:
        return {}
    cur.execute(
        """
        SELECT submitter_team_id, target_team_id, service_id, tick_issued, payload
        FROM submissions
        WHERE result = 'accepted'
          AND tick_issued IS NOT NULL
          AND service_id IS NOT NULL
          AND payload IS NOT NULL
          AND submitter_team_id IS NOT NULL
          AND target_team_id IS NOT NULL
          AND submitted_at < (SELECT starts_at FROM flag_rounds WHERE tick = %s);
        """,
        (current_tick,),
    )
    out: Dict[Tuple[int, int, int], Dict[int, Set[int]]] = defaultdict(lambda: defaultdict(set))
    window_min = max(1, current_tick - retention + 1) - 1
    for row in cur.fetchall():
        tick_issued = int(row["tick_issued"])
        if tick_issued <= window_min - retention:
            continue
        fk = (tick_issued, int(row["service_id"]), int(row["payload"]))
        out[fk][int(row["submitter_team_id"])].add(int(row["target_team_id"]))
    return {k: dict(v) for k, v in out.items()}


def _load_flags_for_tick(
    cur: Any, current_tick: int
) -> List[StolenFlag]:
    """Load accepted submissions that landed during ``current_tick`` and
    populate ``num_previous_submissions`` / ``previous_submitter_ids`` from
    earlier ticks."""
    cur.execute(
        """
        SELECT submitter_team_id, target_team_id, service_id, tick_issued, payload, flag
        FROM submissions
        WHERE result = 'accepted'
          AND tick_issued IS NOT NULL
          AND service_id IS NOT NULL
          AND payload IS NOT NULL
          AND submitted_at >= (SELECT starts_at FROM flag_rounds WHERE tick = %s)
          AND submitted_at <  (SELECT ends_at   FROM flag_rounds WHERE tick = %s);
        """,
        (current_tick, current_tick),
    )
    this_tick_rows = cur.fetchall()
    if not this_tick_rows:
        return []

    # Bucket-by-flag count of this-tick submitters (typically 1 per
    # (submitter, flag) thanks to the dedup constraint).
    this_tick_by_flag: Dict[str, Set[int]] = defaultdict(set)
    for row in this_tick_rows:
        this_tick_by_flag[row["flag"]].add(int(row["submitter_team_id"]))

    flag_strs = list(this_tick_by_flag.keys())
    cur.execute(
        """
        SELECT submitter_team_id, flag
        FROM submissions
        WHERE result = 'accepted'
          AND flag = ANY(%s)
          AND submitted_at < (SELECT starts_at FROM flag_rounds WHERE tick = %s);
        """,
        (flag_strs, current_tick),
    )
    prev_subs_by_flag: Dict[str, Set[int]] = defaultdict(set)
    for row in cur.fetchall():
        prev_subs_by_flag[row["flag"]].add(int(row["submitter_team_id"]))

    flags: List[StolenFlag] = []
    for row in this_tick_rows:
        flag = row["flag"]
        prev_subs = prev_subs_by_flag.get(flag, set())
        new_subs = this_tick_by_flag.get(flag, set())
        flags.append(
            StolenFlag(
                target_team_id=int(row["target_team_id"]),
                submitter_team_id=int(row["submitter_team_id"]),
                service_id=int(row["service_id"]),
                tick_issued=int(row["tick_issued"]),
                payload=int(row["payload"]),
                flag=flag,
                num_previous_submissions=len(prev_subs),
                num_submissions=len(new_subs),
                previous_submitter_ids=sorted(prev_subs),
            )
        )
    return flags


def _persist_tick_points(
    cur: Any, tick: int, new_points: Dict[Tuple[int, int], TeamPointsLite]
) -> None:
    for (team_id, service_id), tp in new_points.items():
        cur.execute(
            """
            INSERT INTO team_tick_points (
                tick, team_id, service_id,
                off_points, def_points, sla_points, sla_delta,
                flag_captured_count, flag_stolen_count
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tick, team_id, service_id) DO UPDATE SET
                off_points = EXCLUDED.off_points,
                def_points = EXCLUDED.def_points,
                sla_points = EXCLUDED.sla_points,
                sla_delta = EXCLUDED.sla_delta,
                flag_captured_count = EXCLUDED.flag_captured_count,
                flag_stolen_count = EXCLUDED.flag_stolen_count;
            """,
            (
                tick, team_id, service_id,
                tp.off_points, tp.def_points, tp.sla_points, tp.sla_delta,
                tp.flag_captured_count, tp.flag_stolen_count,
            ),
        )


def _refresh_scores_summary(cur: Any) -> None:
    """Recompute the `scores` summary table from the latest team_tick_points
    rows so the existing scoreboard UI keeps working."""
    cur.execute(
        """
        WITH latest AS (
            SELECT DISTINCT ON (team_id, service_id)
                team_id, service_id, off_points, def_points, sla_points,
                flag_captured_count, flag_stolen_count, tick
            FROM team_tick_points
            ORDER BY team_id, service_id, tick DESC
        ),
        per_team AS (
            SELECT
                team_id,
                SUM(off_points) AS attack_points,
                SUM(def_points) AS defense_points,
                SUM(sla_points) AS sla_points,
                SUM(off_points + def_points) AS challenge_points,
                SUM((off_points + def_points) * sla_points) AS total
            FROM latest
            GROUP BY team_id
        )
        UPDATE scores sc
        SET attack_points         = COALESCE(p.attack_points, 0),
            defense_points        = COALESCE(p.defense_points, 0),
            uptime_points         = COALESCE(p.sla_points, 0),
            hacked_penalty_points = 0,
            challenge_points      = COALESCE(p.challenge_points, 0),
            sla_points            = CASE WHEN svc.service_count = 0 THEN 0
                                         ELSE COALESCE(p.sla_points, 0) / svc.service_count END,
            total                 = COALESCE(p.total, 0),
            updated_at            = NOW()
        FROM teams t
        LEFT JOIN per_team p ON p.team_id = t.id
        CROSS JOIN (SELECT COUNT(*)::numeric AS service_count FROM services) svc
        WHERE sc.team_id = t.id;
        """
    )


def _snapshot_to_score_table(cur: Any, tick: int) -> None:
    """Mirror this-tick team_tick_points into score_snapshots so the existing
    delta/UI machinery in main.py still works."""
    round_id = _round_id_for_tick(cur, tick)
    if round_id is None:
        return
    cur.execute(
        """
        INSERT INTO score_snapshots (
            round_id, team_id, service_id,
            attack_points, defense_points, uptime_points,
            hacked_penalty_points, challenge_points, service_total,
            flags_captured,
            attackers_count, victims_count,
            sla_up_count, sla_total_count
        )
        SELECT
            %(round_id)s,
            ttp.team_id,
            ttp.service_id,
            ttp.off_points,
            ttp.def_points,
            ttp.sla_points,
            0,
            ttp.off_points + ttp.def_points,
            (ttp.off_points + ttp.def_points) * ttp.sla_points,
            ttp.flag_captured_count,
            COALESCE((
                SELECT COUNT(DISTINCT submitter_team_id)
                FROM submissions
                WHERE result = 'accepted'
                  AND target_team_id = ttp.team_id
                  AND service_id = ttp.service_id
            ), 0),
            ttp.flag_stolen_count,
            (SELECT COUNT(*) FROM service_health sh
             WHERE sh.team_id = ttp.team_id AND sh.service_id = ttp.service_id
               AND sh.tick IS NOT NULL AND sh.tick <= %(tick)s
               AND sh.status IN ('SUCCESS','RECOVERING')),
            (SELECT COUNT(*) FROM service_health sh
             WHERE sh.team_id = ttp.team_id AND sh.service_id = ttp.service_id
               AND sh.tick IS NOT NULL AND sh.tick <= %(tick)s)
        FROM team_tick_points ttp
        WHERE ttp.tick = %(tick)s
        ON CONFLICT (round_id, team_id, service_id)
        DO UPDATE SET
            attack_points = EXCLUDED.attack_points,
            defense_points = EXCLUDED.defense_points,
            uptime_points = EXCLUDED.uptime_points,
            hacked_penalty_points = EXCLUDED.hacked_penalty_points,
            challenge_points = EXCLUDED.challenge_points,
            service_total = EXCLUDED.service_total,
            flags_captured = EXCLUDED.flags_captured,
            attackers_count = EXCLUDED.attackers_count,
            victims_count = EXCLUDED.victims_count,
            sla_up_count = EXCLUDED.sla_up_count,
            sla_total_count = EXCLUDED.sla_total_count;
        """,
        {"round_id": round_id, "tick": tick},
    )


def _score_tick(cur: Any, tick: int, retention: int) -> None:
    if tick < 1:
        return
    services = _load_services(cur)
    team_ids, nop_id = _load_team_ids(cur)
    if not services or not team_ids:
        return

    ticks_to_load = sorted({tick} | {t for t in range(max(1, tick - retention + 1), tick + 1)})
    checker_results = _load_checker_results(cur, ticks_to_load)
    num_active = _load_num_active(cur, ticks_to_load)
    last_points = _load_last_tick_points(cur, tick - 1)
    prev_attacking = _load_prev_attacking(cur, tick, retention)
    flags = _load_flags_for_tick(cur, tick)

    new_points, _new_attacking = calculate_scoring_for_tick(
        current_tick=tick,
        services=services,
        team_ids=team_ids,
        nop_team_id=nop_id,
        retention=retention,
        checker_results=checker_results,
        last_tick_points=last_points,
        prev_attacking=prev_attacking,
        num_active=num_active,
        flags=flags,
    )

    _persist_tick_points(cur, tick, new_points)
    _snapshot_to_score_table(cur, tick)
    _refresh_scores_summary(cur)


# -----------------------------------------------------------------------------
# Main loop
# -----------------------------------------------------------------------------


def _enumerate_team_services(cur: Any, *, include_nop: bool = True) -> List[Dict[str, Any]]:
    cur.execute(
        """
        SELECT
            ts.team_id,
            t.name AS team_name,
            t.is_nop,
            ts.service_id,
            s.name AS service_name,
            s.num_payloads,
            s.flags_per_tick,
            ts.host,
            ts.port
        FROM team_services ts
        JOIN teams t ON t.id = ts.team_id
        JOIN services s ON s.id = ts.service_id
        WHERE ts.enabled = TRUE
        ORDER BY t.name ASC, s.name ASC;
        """
    )
    rows: List[Dict[str, Any]] = []
    for row in cur.fetchall():
        if not include_nop and row["is_nop"]:
            continue
        rows.append(dict(row))
    return rows


def _run_tick_boundary(round_id: int, starts_at: dt.datetime, ends_at: dt.datetime) -> None:
    with get_cursor(commit=True) as (_conn, cur):
        tick = _ensure_flag_round(cur, round_id, starts_at, ends_at)
        retention = _retention_ticks()

        # 1) Score the previous tick only after its distributed checker jobs
        #    are terminal or have crossed their tick deadline.
        if tick > 1:
            overdue = finalize_overdue_checker_jobs(cur, tick=tick - 1)
            if overdue:
                write_log(
                    "checker",
                    f"Marked {overdue} overdue checker jobs as TIMEOUT",
                    f"tick={tick - 1}",
                    LogLevel.WARNING,
                    cur=cur,
                )
            if checker_tick_ready(cur, tick=tick - 1):
                _score_tick(cur, tick - 1, retention)
                write_log(
                    "game",
                    f"Tick {tick - 1} scored",
                    "",
                    LogLevel.IMPORTANT,
                    cur=cur,
                )
            else:
                write_log(
                    "checker",
                    f"Tick {tick - 1} scoring deferred",
                    "checker jobs are still running",
                    LogLevel.WARNING,
                    cur=cur,
                )

        team_services = _enumerate_team_services(cur, include_nop=True)

    # 2) Queue checker work for the new tick. Dedicated Celery workers execute
    #    the jobs and materialize final rows into service_health.
    job_ids = schedule_checker_jobs(
        tick=tick,
        round_id=round_id,
        deadline_at=ends_at,
        team_services=team_services,
    )
    log_checker_tick_summary(tick)
    with get_cursor(commit=True) as (_conn, cur):
        write_log(
            "game",
            f"Tick {tick} checker jobs queued",
            f"round_id={round_id} jobs={len(job_ids)}",
            LogLevel.IMPORTANT,
            cur=cur,
        )


def main() -> None:
    bootstrap_database()
    # Wiki/patches schema is owned by the API, but the rotator may boot first
    # in a fresh deploy. Idempotent CREATE TABLE IF NOT EXISTS keeps both safe.
    try:
        from .patches_api import bootstrap_patches_table
        from .wiki_api import bootstrap_wiki_table
        bootstrap_patches_table()
        bootstrap_wiki_table()
    except Exception as exc:
        print(f"[rotator] WARNING: aux table bootstrap failed: {exc!r}", flush=True)
    rotation = rotation_seconds()
    print(
        f"[rotator] started rotation_seconds={rotation} retention={_retention_ticks()}",
        flush=True,
    )

    while True:
        try:
            with get_cursor(commit=True) as (_conn, cur):
                timer = load_timer(cur)
                timer.sync_scheduled_start(cur)
                timer.load(cur)

                if timer.state == CTFState.RUNNING and timer.current_tick >= 1:
                    cur.execute(
                        "SELECT 1 FROM checker_jobs WHERE tick = %s LIMIT 1;",
                        (timer.current_tick,),
                    )
                    if cur.fetchone() is None and timer.tick_start and timer.tick_end:
                        tick = timer.current_tick
                        round_start = dt.datetime.utcfromtimestamp(timer.tick_start)
                        round_end = dt.datetime.utcfromtimestamp(timer.tick_end)
                        _run_tick_boundary(tick, round_start, round_end)
                        print(f"[rotator] bootstrap checkers tick={tick}", flush=True)

                ready = timer.boundary_ready()
                if ready is not None:
                    tick, round_start, round_end = ready
                    write_log(
                        "game",
                        f"Tick {tick} started",
                        "",
                        LogLevel.IMPORTANT,
                        cur=cur,
                    )
                    _run_tick_boundary(tick, round_start, round_end)
                    timer.finish_boundary(cur)
                    print(f"[rotator] tick boundary handled tick={tick}", flush=True)
        except Exception as exc:
            print(f"[rotator] ERROR: {exc!r}", flush=True)
            try:
                write_log("rotator", "Rotator error", repr(exc), LogLevel.ERROR)
            except Exception:
                pass

        time.sleep(0.5)


if __name__ == "__main__":
    main()
