"""Desired-state lifecycle management for team vulnboxes."""

from __future__ import annotations

import os
import subprocess
from typing import Any, Dict, List, Optional

from .db import get_cursor


VALID_ACTIONS = {"start", "stop", "restart", "reset", "rebuild"}
VALID_DESIRED = {"RUNNING", "STOPPED"}


def compose_services_for_team(team_name: str) -> List[str]:
    service_count = int(os.getenv("VULNBOX_SERVICE_COUNT", "5"))
    return [f"{team_name}-svc{i}" for i in range(1, service_count + 1)]


def docker_compose_command(team_name: str, action: str) -> List[str]:
    compose = os.getenv("VULNBOX_COMPOSE_BIN", "docker compose").split()
    compose_file = os.getenv("VULNBOX_COMPOSE_FILE", "").strip()
    project = os.getenv("VULNBOX_COMPOSE_PROJECT", "kossim").strip()
    cmd = list(compose)
    if compose_file:
        cmd.extend(["-f", compose_file])
    if project:
        cmd.extend(["-p", project])
    services = compose_services_for_team(team_name)
    if action == "start":
        return cmd + ["up", "-d", *services]
    if action == "stop":
        return cmd + ["stop", *services]
    if action == "restart":
        return cmd + ["restart", *services]
    if action == "reset":
        return cmd + ["rm", "-sfv", *services]
    if action == "rebuild":
        return cmd + ["up", "-d", "--build", "--force-recreate", *services]
    raise ValueError(f"unsupported vulnbox action: {action}")


def docker_compose_followup_command(team_name: str, action: str) -> Optional[List[str]]:
    if action != "reset":
        return None
    compose = os.getenv("VULNBOX_COMPOSE_BIN", "docker compose").split()
    compose_file = os.getenv("VULNBOX_COMPOSE_FILE", "").strip()
    project = os.getenv("VULNBOX_COMPOSE_PROJECT", "kossim").strip()
    cmd = list(compose)
    if compose_file:
        cmd.extend(["-f", compose_file])
    if project:
        cmd.extend(["-p", project])
    return cmd + ["up", "-d", *compose_services_for_team(team_name)]


def ensure_vulnboxes(cur: Any) -> None:
    cur.execute(
        """
        SELECT t.id, t.name, tn.vulnbox_ip
        FROM teams t
        LEFT JOIN team_networks tn ON tn.team_id = t.id
        ORDER BY t.id;
        """
    )
    for row in cur.fetchall():
        cur.execute(
            """
            INSERT INTO vulnboxes (team_id, backend, desired_status, observed_status, host, ip_address)
            VALUES (%s, 'docker', 'RUNNING', 'UNKNOWN', %s, %s)
            ON CONFLICT (team_id, backend)
            DO UPDATE SET
                host = COALESCE(vulnboxes.host, EXCLUDED.host),
                ip_address = COALESCE(vulnboxes.ip_address, EXCLUDED.ip_address),
                updated_at = NOW();
            """,
            (int(row["id"]), f"{row['name']}-vulnbox", row["vulnbox_ip"]),
        )


def record_vulnbox_event(
    cur: Any,
    *,
    vulnbox_id: Optional[int],
    team_id: Optional[int],
    action: str,
    status: str,
    message: str,
) -> None:
    cur.execute(
        """
        INSERT INTO vulnbox_events (vulnbox_id, team_id, action, status, message)
        VALUES (%s, %s, %s, %s, %s);
        """,
        (vulnbox_id, team_id, action, status, message),
    )


def _set_observed_status(cur: Any, vulnbox_id: int, status: str, message: str = "") -> None:
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
    if row:
        record_vulnbox_event(
            cur,
            vulnbox_id=vulnbox_id,
            team_id=int(row["team_id"]),
            action="status",
            status=status,
            message=message,
        )


def run_vulnbox_action(vulnbox_id: int, action: str, celery_task_id: Optional[str] = None) -> str:
    if action not in VALID_ACTIONS:
        raise ValueError(f"unsupported vulnbox action: {action}")
    with get_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """
            SELECT vb.*, t.name AS team_name
            FROM vulnboxes vb
            JOIN teams t ON t.id = vb.team_id
            WHERE vb.id = %s
            FOR UPDATE;
            """,
            (vulnbox_id,),
        )
        row = cur.fetchone()
        if not row:
            return "MISSING"
        team_id = int(row["team_id"])
        team_name = row["team_name"]
        record_vulnbox_event(
            cur,
            vulnbox_id=vulnbox_id,
            team_id=team_id,
            action=action,
            status="RUNNING",
            message=f"task={celery_task_id or ''}",
        )

    cmd = docker_compose_command(team_name, action)
    timeout = int(os.getenv("VULNBOX_ACTION_TIMEOUT", "120"))
    try:
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout)
        followup = docker_compose_followup_command(team_name, action)
        if completed.returncode == 0 and followup is not None:
            followup_completed = subprocess.run(
                followup,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            completed = followup_completed
    except Exception as exc:
        with get_cursor(commit=True) as (_conn, cur):
            record_vulnbox_event(
                cur,
                vulnbox_id=vulnbox_id,
                team_id=team_id,
                action=action,
                status="FAILED",
                message=repr(exc),
            )
            _set_observed_status(cur, vulnbox_id, "ERROR", repr(exc))
        return "FAILED"

    out = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
    status = "OK" if completed.returncode == 0 else "FAILED"
    desired = "RUNNING" if action in {"start", "restart", "reset", "rebuild"} else "STOPPED"
    observed = desired if status == "OK" else "ERROR"
    with get_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """
            UPDATE vulnboxes
            SET observed_status = %s, desired_status = %s, updated_at = NOW(), last_report_at = NOW()
            WHERE id = %s;
            """,
            (observed, desired, vulnbox_id),
        )
        record_vulnbox_event(
            cur,
            vulnbox_id=vulnbox_id,
            team_id=team_id,
            action=action,
            status=status,
            message=out[-4000:],
        )
    return status


def enqueue_vulnbox_action(vulnbox_id: int, action: str) -> str:
    from .worker import run_vulnbox_action_task

    result = run_vulnbox_action_task.apply_async(args=[vulnbox_id, action], queue="vulnboxes")
    return str(result.id)


def serialize_vulnbox(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": int(row["id"]),
        "team_id": int(row["team_id"]),
        "team": row.get("team") or row.get("team_name"),
        "backend": row["backend"],
        "desired_status": row["desired_status"],
        "observed_status": row["observed_status"],
        "host": row["host"],
        "ip_address": row["ip_address"],
        "reset_generation": int(row["reset_generation"] or 0),
        "restart_generation": int(row["restart_generation"] or 0),
        "rebuild_generation": int(row["rebuild_generation"] or 0),
        "last_report_at": row["last_report_at"].isoformat() if row["last_report_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }
