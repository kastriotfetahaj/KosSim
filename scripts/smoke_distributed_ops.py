#!/usr/bin/env python3
"""Bounded live smoke for Redis, checker-worker, rotator, and checker jobs."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], *, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False, env=env)
    if check and proc.returncode != 0:
        if proc.stdout:
            print(proc.stdout, file=sys.stderr)
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
        raise subprocess.CalledProcessError(proc.returncode, proc.args, output=proc.stdout, stderr=proc.stderr)
    return proc


def compose(*args: str, env: dict[str, str], project: str) -> subprocess.CompletedProcess[str]:
    return run(["docker", "compose", "-p", project, *args], env=env)


def psql(sql: str, env: dict[str, str], project: str) -> str:
    proc = compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "kossim",
        "-d",
        "kossim",
        "-At",
        "-c",
        sql,
        env=env,
        project=project,
    )
    return proc.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a live distributed checker smoke against docker compose.")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--rotation-seconds", type=int, default=20)
    parser.add_argument("--project", default="kossim-smoke")
    parser.add_argument("--keep-running", action="store_true")
    args = parser.parse_args()

    env = os.environ.copy()
    env.setdefault("POSTGRES_PASSWORD", "dev-pg-pass")
    env.setdefault("SERVICE_PUSH_SECRET", "dev-service-secret")
    env.setdefault("SECRET_FLAG_KEY", "dev-flag-hmac-key")
    env.setdefault("ADMIN_USERNAME", "admin")
    env.setdefault("ADMIN_PASSWORD", "admin")
    env.setdefault("ADMIN_SESSION_SECRET", "dev-session-secret-replace")
    env.setdefault("GAME_ADMIN_TOKEN", "dev-admin-token")
    env["ROTATION_SECONDS"] = str(args.rotation_seconds)
    env["GAME_AUTO_START"] = "1"
    env["CHECKER_WORKER_CONCURRENCY"] = env.get("CHECKER_WORKER_CONCURRENCY", "2")

    services = [
        "redis",
        "postgres",
        "control-api",
        "checker-worker",
        "flag-rotator",
        "team1-svc1",
        "team2-svc1",
        "nop-svc1",
    ]
    try:
        compose("up", "-d", "--build", *services, env=env, project=args.project)
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            try:
                rows = psql(
                    "SELECT COALESCE(COUNT(*),0) FROM checker_jobs WHERE tick >= 1;",
                    env,
                    args.project,
                )
                done = psql(
                    "SELECT COALESCE(COUNT(*),0) FROM checker_jobs WHERE tick >= 1 AND status IN ('SUCCESS','RECOVERING','MUMBLE','OFFLINE','TIMEOUT','CRASHED');",
                    env,
                    args.project,
                )
                health = psql(
                    "SELECT COALESCE(COUNT(*),0) FROM service_health WHERE tick >= 1;",
                    env,
                    args.project,
                )
                if int(rows or "0") > 0 and int(done or "0") > 0 and int(health or "0") > 0:
                    summary = psql(
                        "SELECT status || '=' || COUNT(*) FROM checker_jobs WHERE tick >= 1 GROUP BY status ORDER BY status;",
                        env,
                        args.project,
                    )
                    print("distributed smoke ok")
                    print(summary)
                    return 0
            except Exception as exc:
                last = exc
            time.sleep(3)
        print(f"smoke timed out: {last!r}", file=sys.stderr)
        return 1
    finally:
        if not args.keep_running:
            compose("down", "--remove-orphans", env=env, project=args.project)


if __name__ == "__main__":
    raise SystemExit(main())
