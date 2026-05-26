#!/usr/bin/env python3
"""
Sync entry point used by the KosSim platform driver. Drives one full PUT/GET
cycle across the three ledgerforge flagstores plus the HAVOC surface against
the service base passed as argv[1]. Prints a single JSON line on stdout.
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
    r = requests.post(f"{base}/", json=payload, headers=header(), timeout=8)
    r.raise_for_status()
    return r.json()


def workflow(base: str) -> None:
    tick = random.randint(50, 9000)
    sess = requests.Session()

    info = sess.get(f"{base}/service", headers=header(), timeout=5).json()
    for axis in ("flagVariants", "noiseVariants"):
        if int(info.get(axis, 0)) < 3:
            raise RuntimeError(f"info missing on {axis}")

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

    docs = sess.get(f"{base}/api/docs", timeout=5).json().get("docs")
    if not isinstance(docs, list) or not docs:
        raise RuntimeError("docs listing empty")
    grant = sess.get(f"{base}/api/grants/guest-mirror", timeout=5).json().get("grant")
    if not isinstance(grant, str) or len(grant) < 16:
        raise RuntimeError("grant issue failed")
    welcome = sess.get(
        f"{base}/api/read",
        params={"path": "/public/welcome", "grant": grant},
        timeout=5,
    ).json()
    if "LedgerForge" not in str(welcome.get("body", "")):
        raise RuntimeError("public welcome read failed")
    query_resp = sess.post(f"{base}/api/query", json={"script": "LIST:public"}, timeout=5).json()
    if not isinstance(query_resp.get("rows"), list):
        raise RuntimeError("query desk failed")
    digest = sess.get(f"{base}/debug/merkle", timeout=5).json()
    if len(str(digest.get("root", ""))) < 16:
        raise RuntimeError("merkle digest failed")
    snap = sess.get(
        f"{base}/api/snapshots/boot/export",
        params={"claim": "public:welcome-ledger"},
        timeout=5,
    ).json()
    if not any(row.get("id") == "welcome-ledger" for row in snap.get("rows") or []):
        raise RuntimeError("snapshot export missed welcome doc")


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080").rstrip("/")
    random.seed(f"ledgerforge:{base}:{time.time_ns()}")
    try:
        workflow(base)
    except requests.RequestException as exc:
        return fail("DOWN", str(exc))
    except Exception as exc:  # noqa: BLE001  surfaces to operator as MUMBLE
        return fail("MUMBLE", str(exc))
    print(json.dumps({"status": "OK", "service": "ledgerforge"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
