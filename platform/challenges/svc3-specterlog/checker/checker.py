#!/usr/bin/env python3
"""
Sync wrapper around the SpecterLog enochecker3 logic. Used by the legacy
KosSim platform driver. Drives one full PUT_FLAG + GET_FLAG cycle for all
three flagstores plus a sample of HAVOC probes against the service base
passed as argv[1]. Prints a single JSON line to stdout, exit code 0 on OK.
"""

from __future__ import annotations

import json
import os
import random
import string
import sys
import time
from typing import Any

import requests

ALPHABET = string.ascii_lowercase + string.digits


def rnd(n: int = 12) -> str:
    return "".join(random.choice(ALPHABET) for _ in range(n))


def secret() -> str:
    return os.environ.get("SERVICE_PUSH_SECRET", "rotate-secret")


def header() -> dict[str, str]:
    return {"X-Checker-Secret": secret(), "Content-Type": "application/json"}


def fail(status: str, message: str) -> int:
    print(json.dumps({"status": status, "message": message}))
    return 1


def task(
    base: str,
    method: str,
    tick: int,
    variant: int,
    flag: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "task_id": random.randint(1, 1 << 30),
        "method": method,
        "current_round_id": tick,
        "related_round_id": tick,
        "variant_id": variant,
        "timeout": 8000,
        "round_length": 60_000,
        "flag": flag,
    }
    r = requests.post(f"{base}/", json=payload, headers=header(), timeout=8)
    r.raise_for_status()
    return r.json()


def workflow(base: str) -> None:
    tick = random.randint(50, 9000)
    sess = requests.Session()

    info = sess.get(f"{base}/service", headers=header(), timeout=5).json()
    for axis in ("flagVariants", "noiseVariants", "havocVariants"):
        if int(info.get(axis, 0)) < 3 and axis != "havocVariants":
            raise RuntimeError(f"info missing variants on {axis}")

    flags = {v: f"FLAG{{SYNC_{rnd(8)}_{tick}_{v}}}" for v in (0, 1, 2)}
    attack_infos: dict[int, dict[str, Any]] = {}
    for v in (0, 1, 2):
        put = task(base, "PUTFLAG", tick, v, flag=flags[v])
        if put.get("result") != "OK":
            raise RuntimeError(f"PUTFLAG v{v}: {put}")
        attack_infos[v] = json.loads(put.get("attack_info") or "{}")

    for v in (0, 1, 2):
        get = task(base, "GETFLAG", tick, v, flag=flags[v])
        if get.get("result") != "OK":
            raise RuntimeError(f"GETFLAG v{v}: {get}")

    for v in (0, 1, 2):
        if task(base, "PUTNOISE", tick, v).get("result") != "OK":
            raise RuntimeError(f"PUTNOISE v{v}")
        if task(base, "GETNOISE", tick, v).get("result") != "OK":
            raise RuntimeError(f"GETNOISE v{v}")

    for v in range(9):
        if task(base, "HAVOC", tick, v).get("result") != "OK":
            raise RuntimeError(f"HAVOC v{v}")

    # workflow probes — exercise the public surface beyond raw RPC
    events = sess.get(f"{base}/api/events", timeout=5).json().get("events")
    if not isinstance(events, list) or not events:
        raise RuntimeError("events listing empty")
    cursor = sess.get(f"{base}/api/cursor/public", timeout=5).json().get("cursor")
    if not isinstance(cursor, str) or len(cursor) < 16:
        raise RuntimeError("cursor issue failed")
    replay = sess.get(
        f"{base}/api/replay",
        params={"cursor": cursor},
        timeout=5,
    ).json()
    if not isinstance(replay.get("events"), list):
        raise RuntimeError("replay failed")
    search = sess.get(
        f"{base}/api/search",
        params={"project": "meta", "filter": "public"},
        timeout=5,
    ).json()
    for row in search.get("rows") or []:
        if "body" in row:
            raise RuntimeError("search meta projection leaked body")
    archive = events[0].get("archive")
    if isinstance(archive, str):
        body = sess.get(f"{base}/api/archive/{archive}", timeout=5).json()
        if body.get("archive") != archive:
            raise RuntimeError("archive read failed")

    # registration round trip
    username = f"sync_{rnd(8)}"
    password = rnd(20)
    r = sess.post(
        f"{base}/api/accounts/register",
        json={"username": username, "password": password},
        timeout=5,
    )
    if r.status_code not in (200, 409):
        raise RuntimeError(f"register http {r.status_code}")

    # flagstore-1 round trip: verified via internal GETFLAG above. The share
    # endpoint is exercised by HAVOC v3, which signs server-side and avoids
    # client-side reconstruction of the canonical payload.


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080").rstrip("/")
    random.seed(f"specterlog:{base}:{time.time_ns()}")
    try:
        workflow(base)
    except requests.RequestException as exc:
        return fail("DOWN", str(exc))
    except Exception as exc:  # noqa: BLE001  surfaces to operator as MUMBLE
        return fail("MUMBLE", str(exc))
    print(json.dumps({"status": "OK", "service": "specterlog"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
