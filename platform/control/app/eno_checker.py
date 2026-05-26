"""Tiny Eno-protocol checker client used by the rotator.

Each challenge service exposes the (subset of the) `enochecker_core`
JSON protocol that we need:

    GET  /service        -> CheckerInfoMessage  {serviceName, flagVariants,
                                                 noiseVariants, havocVariants}
    POST /                -> CheckerTaskMessage (in body)
                             returns CheckerResultMessage
                             {result, message, attack_info}

The rotator runs PUTFLAG and GETFLAG against every (team, service, payload)
combo each tick, plus retroactive GETFLAGs across the retention window so the
SLA can resolve RECOVERING correctly (the same shape ECSC's `eno.py` runner
uses, just stripped of slot scheduling and async).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import requests

from .config import required_env


CheckerStatus = str  # SUCCESS | MUMBLE | OFFLINE | INTERNAL_ERROR | TIMEOUT


def _checker_secret() -> str:
    return required_env("SERVICE_PUSH_SECRET")


def _http_timeout() -> float:
    return float(os.getenv("SERVICE_HTTP_TIMEOUT", "3.0"))


def _eno_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


@dataclass
class CheckerInfo:
    service_name: str
    flag_variants: int
    noise_variants: int
    havoc_variants: int


@dataclass
class TaskResult:
    result: CheckerStatus
    message: Optional[str] = None
    attack_info: Optional[str] = None


def get_service_info(host: str, port: int) -> Optional[CheckerInfo]:
    """Probe the service's /service endpoint. Returns None if unreachable."""
    try:
        resp = requests.get(
            _eno_url(host, port) + "/service",
            timeout=_http_timeout(),
            headers={"X-Checker-Secret": _checker_secret()},
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        body = resp.json()
    except Exception:
        return None
    return CheckerInfo(
        service_name=str(body.get("serviceName", "")),
        flag_variants=int(body.get("flagVariants", 1)),
        noise_variants=int(body.get("noiseVariants", 0)),
        havoc_variants=int(body.get("havocVariants", 0)),
    )


def _post_task(host: str, port: int, body: Dict[str, Any]) -> TaskResult:
    try:
        resp = requests.post(
            _eno_url(host, port),
            json=body,
            timeout=_http_timeout(),
            headers={
                "X-Checker-Secret": _checker_secret(),
                "Content-Type": "application/json",
            },
        )
    except requests.Timeout:
        return TaskResult(result="INTERNAL_ERROR", message="TIMEOUT")
    except requests.RequestException as exc:
        return TaskResult(result="OFFLINE", message=str(exc))
    if resp.status_code != 200:
        return TaskResult(result="OFFLINE", message=f"http {resp.status_code}")
    try:
        data = resp.json()
    except Exception:
        return TaskResult(result="MUMBLE", message="bad json")
    return TaskResult(
        result=str(data.get("result", "INTERNAL_ERROR")),
        message=data.get("message"),
        attack_info=data.get("attack_info"),
    )


def _build_task(
    *,
    method: str,
    flag: Optional[str],
    current_tick: int,
    related_tick: int,
    payload: int,
    address: str,
    attack_info: Optional[str] = None,
    timeout_ms: int = 3000,
    round_length_ms: int = 60000,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "task_id": int(time.time() * 1000) & 0xFFFFFFFF,
        "method": method,
        "address": address,
        "team_id": 0,
        "team_name": "checker",
        "current_round_id": current_tick,
        "related_round_id": related_tick,
        "variant_id": payload,
        "timeout": timeout_ms,
        "round_length": round_length_ms,
        "flag": flag,
        "task_chain_id": f"{method.lower()}_t{related_tick}_v{payload}",
    }
    if attack_info is not None:
        body["attack_info"] = attack_info
    return body


def putflag(
    host: str, port: int, *, flag: str, current_tick: int, related_tick: int, payload: int,
    round_length_ms: int = 60000,
) -> TaskResult:
    return _post_task(host, port, _build_task(
        method="PUTFLAG", flag=flag,
        current_tick=current_tick, related_tick=related_tick, payload=payload,
        address=host, round_length_ms=round_length_ms,
    ))


def getflag(
    host: str, port: int, *, flag: str, current_tick: int, related_tick: int, payload: int,
    attack_info: Optional[str] = None, round_length_ms: int = 60000,
) -> TaskResult:
    return _post_task(host, port, _build_task(
        method="GETFLAG", flag=flag,
        current_tick=current_tick, related_tick=related_tick, payload=payload,
        address=host, attack_info=attack_info, round_length_ms=round_length_ms,
    ))


def havoc(host: str, port: int, *, current_tick: int, payload: int,
          round_length_ms: int = 60000) -> TaskResult:
    return _post_task(host, port, _build_task(
        method="HAVOC", flag=None,
        current_tick=current_tick, related_tick=current_tick, payload=payload,
        address=host, round_length_ms=round_length_ms,
    ))


def putnoise(host: str, port: int, *, current_tick: int, payload: int,
             round_length_ms: int = 60000) -> TaskResult:
    """Plant a noise blob for variant ``payload`` at ``current_tick``."""
    return _post_task(host, port, _build_task(
        method="PUTNOISE", flag=None,
        current_tick=current_tick, related_tick=current_tick, payload=payload,
        address=host, round_length_ms=round_length_ms,
    ))


def getnoise(host: str, port: int, *, current_tick: int, related_tick: int,
             payload: int, round_length_ms: int = 60000) -> TaskResult:
    """Read back a previously planted noise blob.

    ``related_tick`` is the tick during which the corresponding PUTNOISE was
    run; checkers MUST regenerate the same payload deterministically from
    ``related_tick`` + ``payload`` (per the ENOChecker spec)."""
    return _post_task(host, port, _build_task(
        method="GETNOISE", flag=None,
        current_tick=current_tick, related_tick=related_tick, payload=payload,
        address=host, round_length_ms=round_length_ms,
    ))


# Status ladder used to combine multiple per-(team, service, payload) results
# into one overall checker status for the round. Lower index = worse.
_STATUS_RANK: Dict[str, int] = {
    "CRASHED": 0,
    "TIMEOUT": 1,
    "OFFLINE": 2,
    "MUMBLE": 3,
    "FLAGMISSING": 3,
    "RECOVERING": 4,
    "SUCCESS": 5,
}


def downgrade(current: str, new: str) -> str:
    if new not in _STATUS_RANK:
        new = "MUMBLE"
    if current not in _STATUS_RANK:
        return new
    return current if _STATUS_RANK[current] <= _STATUS_RANK[new] else new


def normalize(status: str) -> str:
    """Map eno result strings into the checker-result vocabulary we store."""
    if status in _STATUS_RANK:
        return status
    if status == "OK":
        return "SUCCESS"
    if status == "INTERNAL_ERROR":
        return "CRASHED"
    return "MUMBLE"


def is_up(status: str) -> bool:
    return status in {"SUCCESS", "RECOVERING"}


def is_active(status: str) -> bool:
    """A team is 'active' for scoring purposes when any of its services is
    not fully offline."""
    return status not in {"OFFLINE", "TIMEOUT", "CRASHED"}


# ---------------------------------------------------------------------------
# Per-method status derivation (used by the public scoreboard cell)
# ---------------------------------------------------------------------------

# Stati that indicate the checker couldn't reach the service at all. Used to
# decide whether absent flag_avail entries should be reported as FAIL vs IDLE.
_HARD_DOWN: frozenset = frozenset({"OFFLINE", "INTERNAL_ERROR", "TIMEOUT", "CRASHED"})


def derive_method_statuses(
    overall: str,
    flag_avail: Optional[Dict[str, str]],
    current_tick: Optional[int],
) -> Tuple[str, str, str]:
    """Return (put_status, get_status, havoc_status), each one of OK|FAIL|IDLE.

    Derived purely from the data the rotator already records in
    ``service_health``:

    - **PUT (flag in)** — every flag the rotator stored for ``current_tick``
      is recorded in ``flag_avail`` under key ``"{current_tick}_{payload}"``.
      All ``"OK"`` → OK; any ``"MISSING"`` → FAIL; nothing recorded at all →
      FAIL if the service is hard-down, else IDLE.
    - **GET (flag out)** — entries keyed by prior ticks. Same rules as PUT.
      If no prior ticks exist (the very first round) → IDLE.
    - **HAVOC (uptime)** — the rotator does NOT write to ``flag_avail`` from
      HAVOC, so we infer: SUCCESS/RECOVERING overall → OK; if PUT succeeded
      but ``overall`` says otherwise, the failure must be HAVOC → FAIL;
      anything else (PUT failed, so we can't tell) → IDLE.
    """
    overall = (overall or "OFFLINE").upper()
    avail = flag_avail or {}

    if current_tick is None:
        return "IDLE", "IDLE", "IDLE"
    tick_prefix = f"{current_tick}_"

    put_entries = [v for k, v in avail.items() if k.startswith(tick_prefix)]
    get_entries = [v for k, v in avail.items() if not k.startswith(tick_prefix)]

    if put_entries:
        put_status = "OK" if all(v == "OK" for v in put_entries) else "FAIL"
    elif overall in _HARD_DOWN:
        put_status = "FAIL"
    else:
        put_status = "IDLE"

    if get_entries:
        get_status = "OK" if all(v == "OK" for v in get_entries) else "FAIL"
    elif overall in _HARD_DOWN:
        get_status = "FAIL"
    else:
        get_status = "IDLE"

    if overall in ("SUCCESS", "RECOVERING"):
        havoc_status = "OK"
    elif put_status == "OK" and get_status in ("OK", "IDLE"):
        # PUT worked, GET worked (or wasn't attempted yet) — havoc is the
        # only check left that could have downgraded `overall`.
        havoc_status = "FAIL"
    else:
        havoc_status = "IDLE"

    return put_status, get_status, havoc_status
