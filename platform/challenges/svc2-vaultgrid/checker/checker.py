#!/usr/bin/env python3
"""
Sync checker entry point used by the KosSim platform driver. Drives one
PUTFLAG+GETFLAG cycle for each of the three vaultgrid flagstores, plus
PUTNOISE/GETNOISE/HAVOC variants, plus public-surface probes against the
service base passed as argv[1].
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


def rnd(n: int = 10) -> str:
    return "".join(random.choice(ALPHABET) for _ in range(n))


def secret() -> str:
    return os.environ.get("SERVICE_PUSH_SECRET", "rotate-secret")


def header() -> dict[str, str]:
    return {"X-Checker-Secret": secret(), "Content-Type": "application/json"}


def fail(status: str, message: str) -> int:
    print(json.dumps({"status": status, "message": message}))
    return 1


def task(base: str, method: str, tick: int, variant: int, flag: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "method": method,
        "current_round_id": tick,
        "related_round_id": tick,
        "variant_id": variant,
        "flag": flag,
        "timeout": 8000,
        "round_length": 60_000,
    }
    r = requests.post(f"{base}/", json=payload, headers=header(), timeout=10)
    r.raise_for_status()
    return r.json()


def workflow(base: str) -> None:
    sess = requests.Session()
    info = sess.get(f"{base}/service", headers=header(), timeout=5).json()
    if int(info.get("flagVariants", 0)) < 3:
        raise RuntimeError(f"flagVariants {info.get('flagVariants')} < 3")
    if int(info.get("noiseVariants", 0)) < 3:
        raise RuntimeError(f"noiseVariants {info.get('noiseVariants')} < 3")

    tick = random.randint(100, 8000)
    flags = {v: f"FLAG{{SYNC_{rnd(8)}_{tick}_{v}}}" for v in (0, 1, 2)}
    for v in (0, 1, 2):
        put = task(base, "PUTFLAG", tick, v, flag=flags[v])
        if put.get("result") != "OK":
            raise RuntimeError(f"PUTFLAG v{v}: {put}")
        try:
            json.loads(put.get("attack_info") or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"PUTFLAG v{v}: bad attack_info {exc}") from exc
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

    objects = sess.get(f"{base}/api/objects", timeout=5).json().get("objects")
    if not isinstance(objects, list):
        raise RuntimeError("objects listing missing")
    health = sess.get(f"{base}/health", timeout=5).json()
    if health.get("status") != "up":
        raise RuntimeError("health down")
    whoami = sess.get(f"{base}/whoami", timeout=5).json()
    if not str(whoami.get("runtime", "")).startswith("cpp20"):
        raise RuntimeError("runtime banner mismatch")
    manifests = sess.get(f"{base}/api/crypt/manifests?tenant=public", timeout=5).json()
    if not isinstance(manifests.get("manifests"), list):
        raise RuntimeError("manifest listing missing")
    records = sess.get(f"{base}/api/feed/records?tenant=public", timeout=5).json()
    if not isinstance(records.get("records"), list):
        raise RuntimeError("feed records missing")


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080").rstrip("/")
    random.seed(f"vaultgrid:{base}:{time.time_ns()}")
    try:
        workflow(base)
    except requests.RequestException as exc:
        return fail("DOWN", str(exc))
    except Exception as exc:  # noqa: BLE001  surfaces to operator as MUMBLE
        return fail("MUMBLE", str(exc))
    print(json.dumps({"status": "OK", "service": "vaultgrid"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
