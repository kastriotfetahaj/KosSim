"""DB-backed checker scheduling and worker orchestration."""

from __future__ import annotations

import datetime as dt
import os
import socket
import time
import traceback
from typing import Any, Dict, Iterable, List, Optional

from .checker_executor import CheckerExecutionOutcome, record_health, run_checks_for
from .db import get_cursor
from .event_log import LogLevel, write_log
from .scoring import ServiceSpec


TERMINAL_STATUSES = {
    "SUCCESS",
    "RECOVERING",
    "MUMBLE",
    "OFFLINE",
    "TIMEOUT",
    "CRASHED",
}

ACTIVE_STATUSES = {"QUEUED", "RUNNING", "RETRYING"}


def checker_max_attempts() -> int:
    return max(1, int(os.getenv("CHECKER_MAX_ATTEMPTS", "2")))


def checker_retry_delay_seconds() -> int:
    return max(0, int(os.getenv("CHECKER_RETRY_DELAY_SECONDS", "3")))


def worker_name() -> str:
    return os.getenv("CHECKER_WORKER_NAME") or socket.gethostname()


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_datetime(raw: Any) -> dt.datetime:
    if isinstance(raw, dt.datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=dt.timezone.utc)
        return raw
    return dt.datetime.fromisoformat(str(raw))


def should_retry_exception(
    *,
    attempt_no: int,
    max_attempts: int,
    deadline_at: dt.datetime,
    now: Optional[dt.datetime] = None,
) -> bool:
    current = now or _utc_now()
    if deadline_at.tzinfo is None:
        deadline_at = deadline_at.replace(tzinfo=dt.timezone.utc)
    return attempt_no < max_attempts and deadline_at > current


def _enqueue_checker_job(job_id: int) -> Optional[str]:
    from .worker import run_checker_job_task

    result = run_checker_job_task.apply_async(args=[job_id], queue="checkers")
    return str(result.id)


def update_worker_heartbeat(*, active_jobs: int = 0, name: Optional[str] = None) -> None:
    with get_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """
            INSERT INTO checker_worker_heartbeats (worker_name, last_seen, active_jobs)
            VALUES (%s, NOW(), %s)
            ON CONFLICT (worker_name)
            DO UPDATE SET last_seen = NOW(), active_jobs = EXCLUDED.active_jobs;
            """,
            (name or worker_name(), active_jobs),
        )


def schedule_checker_jobs(
    *,
    tick: int,
    round_id: int,
    deadline_at: dt.datetime,
    team_services: Iterable[Dict[str, Any]],
) -> List[int]:
    """Create one checker job per enabled team-service and enqueue new work.

    This function is idempotent for a tick: an existing job keeps its terminal
    result, while queued/retrying jobs may be re-enqueued if no Celery task id is
    known.
    """
    job_ids: List[int] = []
    to_enqueue: List[int] = []
    with get_cursor(commit=True) as (_conn, cur):
        for item in team_services:
            cur.execute(
                """
                INSERT INTO checker_jobs (
                    tick, round_id, team_id, service_id, host, port,
                    status, max_attempts, deadline_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'QUEUED', %s, %s)
                ON CONFLICT (tick, team_id, service_id)
                DO UPDATE SET
                    round_id = EXCLUDED.round_id,
                    host = EXCLUDED.host,
                    port = EXCLUDED.port,
                    deadline_at = EXCLUDED.deadline_at,
                    max_attempts = EXCLUDED.max_attempts
                WHERE checker_jobs.status NOT IN ('SUCCESS','RECOVERING','MUMBLE','OFFLINE','TIMEOUT','CRASHED')
                RETURNING id, status, celery_task_id;
                """,
                (
                    tick,
                    round_id,
                    int(item["team_id"]),
                    int(item["service_id"]),
                    item["host"],
                    int(item["port"]),
                    checker_max_attempts(),
                    deadline_at,
                ),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    """
                    SELECT id, status, celery_task_id
                    FROM checker_jobs
                    WHERE tick = %s AND team_id = %s AND service_id = %s;
                    """,
                    (tick, int(item["team_id"]), int(item["service_id"])),
                )
                row = cur.fetchone()
            if row is None:
                continue
            job_id = int(row["id"])
            job_ids.append(job_id)
            if row["status"] not in TERMINAL_STATUSES and not row["celery_task_id"]:
                to_enqueue.append(job_id)

    for job_id in to_enqueue:
        try:
            task_id = _enqueue_checker_job(job_id)
        except Exception as exc:
            with get_cursor(commit=True) as (_conn, cur):
                cur.execute("SELECT * FROM checker_jobs WHERE id = %s;", (job_id,))
                job = cur.fetchone()
                if job:
                    _materialize_job_status(
                        cur,
                        job=dict(job),
                        status="CRASHED",
                        message=f"enqueue failed: {exc!r}",
                        runtime_seconds=0.0,
                    )
            continue
        with get_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                UPDATE checker_jobs
                SET celery_task_id = %s
                WHERE id = %s AND status IN ('QUEUED', 'RETRYING');
                """,
                (task_id, job_id),
            )
    return job_ids


def _start_attempt(job_id: int, celery_task_id: Optional[str]) -> Optional[Dict[str, Any]]:
    with get_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """
            SELECT cj.*, t.name AS team_name, s.name AS service_name,
                   s.num_payloads, s.flags_per_tick
            FROM checker_jobs cj
            JOIN teams t ON t.id = cj.team_id
            JOIN services s ON s.id = cj.service_id
            WHERE cj.id = %s
            FOR UPDATE;
            """,
            (job_id,),
        )
        job = cur.fetchone()
        if job is None or job["status"] in TERMINAL_STATUSES or job["status"] == "RUNNING":
            return None
        if _parse_datetime(job["deadline_at"]) <= _utc_now():
            _materialize_job_status(
                cur,
                job=job,
                status="TIMEOUT",
                message="checker job expired before worker start",
                runtime_seconds=0.0,
            )
            return None
        attempt_no = int(job["attempts"] or 0) + 1
        cur.execute(
            """
            INSERT INTO checker_attempts (
                job_id, attempt_no, celery_task_id, worker_name, status
            )
            VALUES (%s, %s, %s, %s, 'RUNNING')
            RETURNING id;
            """,
            (job_id, attempt_no, celery_task_id, worker_name()),
        )
        attempt_id = int(cur.fetchone()["id"])
        cur.execute(
            """
            UPDATE checker_jobs
            SET status = 'RUNNING',
                attempts = %s,
                celery_task_id = COALESCE(%s, celery_task_id),
                started_at = COALESCE(started_at, NOW()),
                last_error = NULL
            WHERE id = %s;
            """,
            (attempt_no, celery_task_id, job_id),
        )
        return {**dict(job), "attempt_id": attempt_id, "attempt_no": attempt_no}


def _materialize_job_status(
    cur: Any,
    *,
    job: Dict[str, Any],
    status: str,
    message: str,
    runtime_seconds: float,
) -> None:
    record_health(
        cur,
        team_id=int(job["team_id"]),
        service_id=int(job["service_id"]),
        round_id=int(job["round_id"]),
        tick=int(job["tick"]),
        status=status,
        message=message,
        attack_info=None,
        flag_avail={},
        runtime_seconds=runtime_seconds,
    )
    cur.execute(
        """
        UPDATE checker_jobs
        SET status = %s,
            result_status = %s,
            runtime_seconds = %s,
            finished_at = NOW(),
            last_error = %s
        WHERE id = %s;
        """,
        (status, status, round(runtime_seconds, 3), message, int(job["id"])),
    )


def _finish_success(job_id: int, attempt_id: int, outcome: CheckerExecutionOutcome) -> None:
    with get_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """
            UPDATE checker_attempts
            SET status = %s, finished_at = NOW(), runtime_seconds = %s
            WHERE id = %s;
            """,
            (outcome.status, round(outcome.runtime_seconds, 3), attempt_id),
        )
        cur.execute(
            """
            UPDATE checker_jobs
            SET status = %s,
                result_status = %s,
                runtime_seconds = %s,
                finished_at = NOW(),
                last_error = NULL
            WHERE id = %s;
            """,
            (outcome.status, outcome.status, round(outcome.runtime_seconds, 3), job_id),
        )


def _finish_exception(job: Dict[str, Any], exc: BaseException, runtime_seconds: float) -> str:
    error = "".join(traceback.TracebackException.from_exception(exc).format())
    job_id = int(job["id"])
    attempt_id = int(job["attempt_id"])
    attempt_no = int(job["attempt_no"])
    max_attempts = int(job["max_attempts"] or checker_max_attempts())
    will_retry = should_retry_exception(
        attempt_no=attempt_no,
        max_attempts=max_attempts,
        deadline_at=_parse_datetime(job["deadline_at"]),
    )
    next_status = "RETRYING" if will_retry else "CRASHED"

    with get_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """
            UPDATE checker_attempts
            SET status = %s, finished_at = NOW(), runtime_seconds = %s, error = %s
            WHERE id = %s;
            """,
            (next_status, round(runtime_seconds, 3), error, attempt_id),
        )
        if will_retry:
            cur.execute(
                """
                UPDATE checker_jobs
                SET status = 'RETRYING',
                    celery_task_id = NULL,
                    last_error = %s
                WHERE id = %s;
                """,
                (error[-8000:], job_id),
            )
        else:
            _materialize_job_status(
                cur,
                job=job,
                status="CRASHED",
                message=f"runner exception: {exc!r}",
                runtime_seconds=runtime_seconds,
            )

    if will_retry:
        time.sleep(checker_retry_delay_seconds())
        try:
            task_id = _enqueue_checker_job(job_id)
            with get_cursor(commit=True) as (_conn, cur):
                cur.execute(
                    "UPDATE checker_jobs SET celery_task_id = %s WHERE id = %s;",
                    (task_id, job_id),
                )
        except Exception as enqueue_exc:
            with get_cursor(commit=True) as (_conn, cur):
                cur.execute(
                    """
                    SELECT * FROM checker_jobs WHERE id = %s;
                    """,
                    (job_id,),
                )
                row = cur.fetchone()
                if row:
                    _materialize_job_status(
                        cur,
                        job=dict(row),
                        status="CRASHED",
                        message=f"retry enqueue failed: {enqueue_exc!r}",
                        runtime_seconds=runtime_seconds,
                    )
    return next_status


def run_checker_job(job_id: int, celery_task_id: Optional[str] = None) -> str:
    update_worker_heartbeat(active_jobs=1)
    job = _start_attempt(job_id, celery_task_id)
    if job is None:
        update_worker_heartbeat(active_jobs=0)
        return "SKIPPED"

    started = time.time()
    try:
        with get_cursor(commit=True) as (_conn, cur):
            service = ServiceSpec(
                id=int(job["service_id"]),
                name=str(job["service_name"]),
                num_payloads=int(job["num_payloads"] or 1),
                flags_per_tick=int(job["flags_per_tick"] or 1),
            )
            outcome = run_checks_for(
                cur,
                team_id=int(job["team_id"]),
                team_name=str(job["team_name"]),
                service=service,
                host=str(job["host"]),
                port=int(job["port"]),
                tick=int(job["tick"]),
                round_id=int(job["round_id"]),
                expires_at=_parse_datetime(job["deadline_at"]),
                retention=max(1, int(os.getenv("FLAG_RETENTION_TICKS", "5"))),
                round_length_ms=int(int(os.getenv("ROTATION_SECONDS", "120")) * 1000),
                job_id=job_id,
                attempt_id=int(job["attempt_id"]),
            )
    except Exception as exc:
        status = _finish_exception(job, exc, time.time() - started)
        update_worker_heartbeat(active_jobs=0)
        return status

    _finish_success(job_id, int(job["attempt_id"]), outcome)
    update_worker_heartbeat(active_jobs=0)
    return outcome.status


def finalize_overdue_checker_jobs(cur: Any, *, tick: int) -> int:
    cur.execute(
        """
        SELECT *
        FROM checker_jobs
        WHERE tick = %s
          AND status IN ('QUEUED', 'RUNNING', 'RETRYING')
          AND deadline_at <= NOW()
        ORDER BY id;
        """,
        (tick,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    for job in rows:
        _materialize_job_status(
            cur,
            job=job,
            status="TIMEOUT",
            message="checker job exceeded tick deadline",
            runtime_seconds=0.0,
        )
        cur.execute(
            """
            UPDATE checker_attempts
            SET status = 'TIMEOUT', finished_at = NOW(), error = COALESCE(error, 'tick deadline exceeded')
            WHERE job_id = %s AND status = 'RUNNING';
            """,
            (int(job["id"]),),
        )
    return len(rows)


def checker_tick_ready(cur: Any, *, tick: int) -> bool:
    cur.execute(
        """
        SELECT COUNT(*) AS n
        FROM checker_jobs
        WHERE tick = %s AND status IN ('QUEUED', 'RUNNING', 'RETRYING');
        """,
        (tick,),
    )
    return int(cur.fetchone()["n"] or 0) == 0


def log_checker_tick_summary(tick: int) -> None:
    with get_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """
            SELECT status, COUNT(*) AS n
            FROM checker_jobs
            WHERE tick = %s
            GROUP BY status
            ORDER BY status;
            """,
            (tick,),
        )
        summary = ", ".join(f"{r['status']}={int(r['n'])}" for r in cur.fetchall())
    write_log("checker", f"Tick {tick} checker jobs", summary, LogLevel.INFO)
