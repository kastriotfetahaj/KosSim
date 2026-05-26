"""Operator observability aggregates and Prometheus-style metrics."""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Optional


RUNTIME_BUCKETS = [0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 25.0, 60.0]


def runtime_histogram(values: Iterable[float]) -> Dict[str, int]:
    buckets = {str(bucket): 0 for bucket in RUNTIME_BUCKETS}
    buckets["+Inf"] = 0
    for raw in values:
        value = float(raw or 0)
        placed = False
        for bucket in RUNTIME_BUCKETS:
            if value <= bucket:
                buckets[str(bucket)] += 1
                placed = True
                break
        if not placed:
            buckets["+Inf"] += 1
    return buckets


def redis_queue_depths() -> Dict[str, Optional[int]]:
    url = os.getenv("REDIS_URL") or os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
    queues = [q.strip() for q in os.getenv("OBS_QUEUE_NAMES", "checkers,vulnboxes,celery").split(",") if q.strip()]
    try:
        import redis

        client = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        return {queue: int(client.llen(queue)) for queue in queues}
    except Exception:
        return {queue: None for queue in queues}


def build_observability(cur: Any, *, ticks: int = 60) -> Dict[str, Any]:
    cur.execute(
        """
        SELECT MAX(tick) AS latest_tick
        FROM flag_rounds;
        """
    )
    latest_tick = int(cur.fetchone()["latest_tick"] or 0)
    start_tick = max(1, latest_tick - ticks + 1) if latest_tick else 0

    cur.execute(
        """
        SELECT COALESCE(runtime_seconds, 0) AS runtime_seconds
        FROM checker_jobs
        WHERE finished_at IS NOT NULL
          AND (%s = 0 OR tick BETWEEN %s AND %s);
        """,
        (latest_tick, start_tick, latest_tick),
    )
    runtimes = [float(r["runtime_seconds"] or 0) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT status, COUNT(*) AS n
        FROM checker_jobs
        WHERE %s = 0 OR tick BETWEEN %s AND %s
        GROUP BY status
        ORDER BY status;
        """,
        (latest_tick, start_tick, latest_tick),
    )
    checker_status = {r["status"]: int(r["n"]) for r in cur.fetchall()}

    cur.execute(
        """
        SELECT COALESCE(NULLIF(s.display_name, ''), s.name) AS service,
               sh.tick,
               ROUND(
                   100.0 * SUM(CASE WHEN sh.is_up THEN 1 ELSE 0 END)::numeric / GREATEST(COUNT(*), 1),
                   2
               ) AS sla
        FROM service_health sh
        JOIN services s ON s.id = sh.service_id
        JOIN teams t ON t.id = sh.team_id
        WHERE sh.tick BETWEEN %s AND %s
          AND t.is_nop = FALSE
        GROUP BY s.id, s.display_name, s.name, sh.tick
        ORDER BY s.id, sh.tick;
        """,
        (start_tick, latest_tick),
    )
    sla_rows = [dict(r) for r in cur.fetchall()] if latest_tick else []

    cur.execute(
        """
        SELECT tick_issued AS tick, result, COUNT(*) AS n
        FROM submissions
        WHERE tick_issued BETWEEN %s AND %s
        GROUP BY tick_issued, result
        ORDER BY tick_issued ASC, result ASC;
        """,
        (start_tick, latest_tick),
    )
    submission_rates = [dict(r) for r in cur.fetchall()] if latest_tick else []

    cur.execute(
        """
        SELECT sub.id, sub.submitted_at, sub.tick_issued, attacker.name AS attacker,
               victim.name AS victim, COALESCE(NULLIF(s.display_name, ''), s.name) AS service
        FROM submissions sub
        JOIN teams attacker ON attacker.id = sub.submitter_team_id
        LEFT JOIN teams victim ON victim.id = sub.target_team_id
        LEFT JOIN services s ON s.id = sub.service_id
        WHERE sub.is_firstblood = TRUE
        ORDER BY sub.submitted_at ASC
        LIMIT 80;
        """
    )
    first_bloods = [
        {
            "id": int(r["id"]),
            "submitted_at": r["submitted_at"].isoformat() if r["submitted_at"] else None,
            "tick": r["tick_issued"],
            "attacker": r["attacker"],
            "victim": r["victim"],
            "service": r["service"],
        }
        for r in cur.fetchall()
    ]

    cur.execute(
        """
        SELECT cj.id, cj.tick, t.name AS team, s.name AS service, cj.status,
               cj.last_error, csl.method, csl.message, csl.trace, csl.created_at
        FROM checker_jobs cj
        JOIN teams t ON t.id = cj.team_id
        JOIN services s ON s.id = cj.service_id
        LEFT JOIN LATERAL (
            SELECT method, message, trace, created_at
            FROM checker_step_logs
            WHERE job_id = cj.id AND status NOT IN ('SUCCESS')
            ORDER BY created_at DESC
            LIMIT 1
        ) csl ON TRUE
        WHERE cj.status NOT IN ('SUCCESS', 'RECOVERING')
        ORDER BY COALESCE(csl.created_at, cj.finished_at, cj.queued_at) DESC
        LIMIT 80;
        """
    )
    failed_checks = [
        {
            "id": int(r["id"]),
            "tick": r["tick"],
            "team": r["team"],
            "service": r["service"],
            "status": r["status"],
            "method": r["method"],
            "message": r["message"] or r["last_error"] or "",
            "trace": r["trace"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in cur.fetchall()
    ]

    cur.execute(
        """
        SELECT worker_name, last_seen, active_jobs
        FROM checker_worker_heartbeats
        ORDER BY last_seen DESC;
        """
    )
    workers = [
        {
            "worker_name": r["worker_name"],
            "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
            "active_jobs": int(r["active_jobs"] or 0),
        }
        for r in cur.fetchall()
    ]

    cur.execute(
        """
        SELECT COUNT(*) AS n
        FROM checker_jobs
        WHERE status IN ('QUEUED', 'RUNNING', 'RETRYING') AND deadline_at < NOW();
        """
    )
    overdue_jobs = int(cur.fetchone()["n"] or 0)

    cur.execute(
        """
        SELECT COUNT(*) AS n
        FROM vulnboxes
        WHERE last_report_at IS NULL OR last_report_at < NOW() - INTERVAL '2 minutes';
        """
    )
    stale_vulnboxes = int(cur.fetchone()["n"] or 0)

    queue_depths = redis_queue_depths()
    alerts = []
    if not workers:
        alerts.append({"severity": "warning", "title": "No checker worker heartbeat", "detail": "No worker has reported activity."})
    if any((depth or 0) > int(os.getenv("OBS_QUEUE_DEPTH_WARN", "100")) for depth in queue_depths.values() if depth is not None):
        alerts.append({"severity": "warning", "title": "High queue depth", "detail": str(queue_depths)})
    if overdue_jobs:
        alerts.append({"severity": "danger", "title": "Overdue checker jobs", "detail": str(overdue_jobs)})
    if checker_status.get("CRASHED", 0) >= int(os.getenv("OBS_CRASH_WARN", "3")):
        alerts.append({"severity": "danger", "title": "Repeated checker crashes", "detail": str(checker_status.get("CRASHED", 0))})
    if stale_vulnboxes:
        alerts.append({"severity": "warning", "title": "Stale vulnbox status", "detail": str(stale_vulnboxes)})

    return {
        "latest_tick": latest_tick,
        "tick_range": {"start": start_tick, "end": latest_tick},
        "queue_depths": queue_depths,
        "checker_status": checker_status,
        "runtime_histogram": runtime_histogram(runtimes),
        "sla_rows": sla_rows,
        "submission_rates": submission_rates,
        "first_bloods": first_bloods,
        "failed_checks": failed_checks,
        "workers": workers,
        "alerts": alerts,
    }


def render_prometheus_metrics(data: Dict[str, Any]) -> str:
    lines: List[str] = []
    for queue, depth in data["queue_depths"].items():
        if depth is not None:
            lines.append(f'kossim_queue_depth{{queue="{queue}"}} {depth}')
    for status, count in data["checker_status"].items():
        lines.append(f'kossim_checker_jobs{{status="{status}"}} {count}')
    cumulative = 0
    for bucket, count in data["runtime_histogram"].items():
        cumulative += int(count)
        lines.append(f'kossim_checker_runtime_seconds_bucket{{le="{bucket}"}} {cumulative}')
    lines.append(f"kossim_alerts {len(data['alerts'])}")
    return "\n".join(lines) + "\n"
