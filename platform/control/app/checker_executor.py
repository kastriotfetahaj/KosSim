"""Worker-safe ENO checker execution for one (tick, team, service) job."""

from __future__ import annotations

import datetime as dt
import json
import os
import time
import traceback
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .eno_checker import (
    CheckerInfo,
    TaskResult,
    downgrade,
    get_service_info,
    getflag as eno_getflag,
    getnoise as eno_getnoise,
    havoc as eno_havoc,
    is_up,
    normalize,
    putflag as eno_putflag,
    putnoise as eno_putnoise,
)
from .flag_crypto import make_flag
from .scoring import ServiceSpec


@dataclass(frozen=True)
class CheckerExecutionOutcome:
    status: str
    runtime_seconds: float


def retention_ticks() -> int:
    return max(1, int(os.getenv("FLAG_RETENTION_TICKS", "5")))


def service_check_budget_seconds() -> float:
    return max(0.0, float(os.getenv("SERVICE_CHECK_BUDGET_SECONDS", "25")))


def havoc_enabled() -> bool:
    return os.getenv("RUN_HAVOC", "1") not in ("0", "false", "False", "")


def noise_enabled() -> bool:
    return os.getenv("RUN_NOISE", "1") not in ("0", "false", "False", "")


def _service_info_for(host: str, port: int, default_payloads: int) -> CheckerInfo:
    info = get_service_info(host, port)
    if info is None:
        return CheckerInfo(
            service_name="",
            flag_variants=default_payloads,
            noise_variants=0,
            havoc_variants=0,
        )
    return info


def _round_id_for_tick(cur: Any, tick: int) -> Optional[int]:
    cur.execute("SELECT round_id FROM flag_rounds WHERE tick = %s;", (tick,))
    row = cur.fetchone()
    return None if row is None else int(row["round_id"])


def _store_putflag_result(
    cur: Any,
    *,
    team_id: int,
    service_id: int,
    round_id: int,
    payload: int,
    flag: str,
    expires_at: dt.datetime,
    attack_info: Optional[str],
) -> None:
    cur.execute(
        """
        UPDATE flags SET active = FALSE
        WHERE team_id = %s AND service_id = %s AND payload = %s AND active = TRUE;
        """,
        (team_id, service_id, payload),
    )
    cur.execute(
        """
        INSERT INTO flags (team_id, service_id, round_id, flag, payload, attack_info,
                           active, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s)
        ON CONFLICT (team_id, service_id, round_id, payload)
        DO UPDATE SET flag = EXCLUDED.flag,
                      attack_info = EXCLUDED.attack_info,
                      active = TRUE,
                      expires_at = EXCLUDED.expires_at;
        """,
        (team_id, service_id, round_id, flag, payload, attack_info, expires_at),
    )


def record_health(
    cur: Any,
    *,
    team_id: int,
    service_id: int,
    round_id: int,
    tick: int,
    status: str,
    message: Optional[str],
    attack_info: Optional[str],
    flag_avail: Dict[str, str],
    runtime_seconds: float,
) -> None:
    cur.execute(
        """
        INSERT INTO service_health (
            team_id, service_id, round_id, tick, is_up, status, message,
            attack_info, flag_avail, runtime_seconds
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
        ON CONFLICT (team_id, service_id, round_id)
        DO UPDATE SET
            tick = EXCLUDED.tick,
            is_up = EXCLUDED.is_up,
            status = EXCLUDED.status,
            message = EXCLUDED.message,
            attack_info = EXCLUDED.attack_info,
            flag_avail = EXCLUDED.flag_avail,
            runtime_seconds = EXCLUDED.runtime_seconds,
            checked_at = NOW();
        """,
        (
            team_id,
            service_id,
            round_id,
            tick,
            is_up(status),
            status,
            message,
            attack_info,
            json.dumps(flag_avail),
            round(runtime_seconds, 3),
        ),
    )


def record_step_log(
    cur: Any,
    *,
    job_id: Optional[int],
    attempt_id: Optional[int],
    method: str,
    related_tick: Optional[int],
    payload: Optional[int],
    status: str,
    message: Optional[str],
    runtime_seconds: float,
    trace: Optional[str] = None,
) -> None:
    if job_id is None:
        return
    cur.execute(
        """
        INSERT INTO checker_step_logs (
            job_id, attempt_id, method, related_tick, payload, status,
            message, runtime_seconds, trace
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
        """,
        (
            job_id,
            attempt_id,
            method,
            related_tick,
            payload,
            status,
            message,
            round(runtime_seconds, 3),
            trace,
        ),
    )


def _run_step(
    cur: Any,
    *,
    job_id: Optional[int],
    attempt_id: Optional[int],
    method: str,
    related_tick: Optional[int],
    payload: Optional[int],
    call: Any,
) -> TaskResult:
    started = time.time()
    try:
        result: TaskResult = call()
        record_step_log(
            cur,
            job_id=job_id,
            attempt_id=attempt_id,
            method=method,
            related_tick=related_tick,
            payload=payload,
            status=normalize(result.result),
            message=result.message,
            runtime_seconds=time.time() - started,
        )
        return result
    except Exception as exc:
        trace = traceback.format_exc()
        record_step_log(
            cur,
            job_id=job_id,
            attempt_id=attempt_id,
            method=method,
            related_tick=related_tick,
            payload=payload,
            status="CRASHED",
            message=repr(exc),
            runtime_seconds=time.time() - started,
            trace=trace,
        )
        raise


def run_checks_for(
    cur: Any,
    *,
    team_id: int,
    team_name: str,
    service: ServiceSpec,
    host: str,
    port: int,
    tick: int,
    round_id: int,
    expires_at: dt.datetime,
    retention: int,
    round_length_ms: int,
    job_id: Optional[int] = None,
    attempt_id: Optional[int] = None,
) -> CheckerExecutionOutcome:
    started = time.time()
    budget_seconds = service_check_budget_seconds()
    deadline = started + budget_seconds if budget_seconds > 0 else None

    def budget_exceeded() -> bool:
        return deadline is not None and time.time() >= deadline

    info = _service_info_for(host, port, service.num_payloads)
    overall = "SUCCESS"
    flag_avail: Dict[str, str] = {}
    last_attack_info: Optional[str] = None
    last_message: Optional[str] = None

    def mark_timeout() -> None:
        nonlocal overall, last_message
        overall = downgrade(overall, "TIMEOUT")
        last_message = last_message or f"service check budget exceeded ({budget_seconds:g}s)"

    for payload in range(min(service.num_payloads, info.flag_variants or service.num_payloads)):
        if budget_exceeded():
            mark_timeout()
            break
        flag_str = make_flag(tick, team_id, service.id, payload)
        result = _run_step(
            cur,
            job_id=job_id,
            attempt_id=attempt_id,
            method="PUTFLAG",
            related_tick=tick,
            payload=payload,
            call=lambda flag_str=flag_str, payload=payload: eno_putflag(
                host,
                port,
                flag=flag_str,
                current_tick=tick,
                related_tick=tick,
                payload=payload,
                round_length_ms=round_length_ms,
            ),
        )
        if result.result == "OK":
            attack_info = result.attack_info
            if attack_info:
                last_attack_info = attack_info
            _store_putflag_result(
                cur,
                team_id=team_id,
                service_id=service.id,
                round_id=round_id,
                payload=payload,
                flag=flag_str,
                expires_at=expires_at,
                attack_info=attack_info,
            )
            flag_avail[f"{tick}_{payload}"] = "OK"
        else:
            overall = downgrade(overall, normalize(result.result))
            last_message = result.message or last_message
            flag_avail[f"{tick}_{payload}"] = "MISSING"

    window_start = max(1, tick - retention + 1)
    for related_tick in range(window_start, tick):
        if budget_exceeded():
            mark_timeout()
            break
        related_round_id = _round_id_for_tick(cur, related_tick)
        for payload in range(min(service.num_payloads, info.flag_variants or service.num_payloads)):
            if budget_exceeded():
                mark_timeout()
                break
            cur.execute(
                "SELECT flag, attack_info FROM flags "
                "WHERE team_id = %s AND service_id = %s AND payload = %s AND round_id = %s;",
                (team_id, service.id, payload, related_round_id),
            )
            row = cur.fetchone()
            if row is None:
                flag_avail[f"{related_tick}_{payload}"] = "MISSING"
                continue
            flag_str = row["flag"]
            attack_info = row["attack_info"]
            result = _run_step(
                cur,
                job_id=job_id,
                attempt_id=attempt_id,
                method="GETFLAG",
                related_tick=related_tick,
                payload=payload,
                call=lambda flag_str=flag_str, related_tick=related_tick, payload=payload, attack_info=attack_info: eno_getflag(
                    host,
                    port,
                    flag=flag_str,
                    current_tick=tick,
                    related_tick=related_tick,
                    payload=payload,
                    attack_info=attack_info,
                    round_length_ms=round_length_ms,
                ),
            )
            if result.result == "OK":
                flag_avail[f"{related_tick}_{payload}"] = "OK"
            else:
                flag_avail[f"{related_tick}_{payload}"] = "MISSING"
                if overall == "SUCCESS":
                    overall = "RECOVERING"
                last_message = result.message or last_message

    if noise_enabled() and info.noise_variants > 0:
        for variant in range(info.noise_variants):
            if budget_exceeded():
                mark_timeout()
                break
            result = _run_step(
                cur,
                job_id=job_id,
                attempt_id=attempt_id,
                method="PUTNOISE",
                related_tick=tick,
                payload=variant,
                call=lambda variant=variant: eno_putnoise(
                    host,
                    port,
                    current_tick=tick,
                    payload=variant,
                    round_length_ms=round_length_ms,
                ),
            )
            if result.result != "OK":
                overall = downgrade(overall, normalize(result.result))
                last_message = result.message or last_message
        for related_tick in range(window_start, tick):
            if budget_exceeded():
                mark_timeout()
                break
            for variant in range(info.noise_variants):
                if budget_exceeded():
                    mark_timeout()
                    break
                result = _run_step(
                    cur,
                    job_id=job_id,
                    attempt_id=attempt_id,
                    method="GETNOISE",
                    related_tick=related_tick,
                    payload=variant,
                    call=lambda related_tick=related_tick, variant=variant: eno_getnoise(
                        host,
                        port,
                        current_tick=tick,
                        related_tick=related_tick,
                        payload=variant,
                        round_length_ms=round_length_ms,
                    ),
                )
                if result.result != "OK":
                    if overall == "SUCCESS":
                        overall = "RECOVERING"
                    last_message = result.message or last_message

    if havoc_enabled() and info.havoc_variants > 0:
        for variant in range(info.havoc_variants):
            if budget_exceeded():
                mark_timeout()
                break
            result = _run_step(
                cur,
                job_id=job_id,
                attempt_id=attempt_id,
                method="HAVOC",
                related_tick=tick,
                payload=variant,
                call=lambda variant=variant: eno_havoc(
                    host,
                    port,
                    current_tick=tick,
                    payload=variant,
                    round_length_ms=round_length_ms,
                ),
            )
            if result.result != "OK":
                overall = downgrade(overall, normalize(result.result))
                last_message = result.message or last_message

    runtime = time.time() - started
    record_health(
        cur,
        team_id=team_id,
        service_id=service.id,
        round_id=round_id,
        tick=tick,
        status=overall,
        message=last_message,
        attack_info=last_attack_info,
        flag_avail=flag_avail,
        runtime_seconds=runtime,
    )
    return CheckerExecutionOutcome(status=overall, runtime_seconds=runtime)
