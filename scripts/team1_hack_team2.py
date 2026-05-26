#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
SOLVERS = {
    "svc1": ROOT / "platform/challenges/svc1-ledgerforge/exploits/solver.py",
    "svc2": ROOT / "platform/challenges/svc2-vaultgrid/exploits/solver.py",
    "svc3": ROOT / "platform/challenges/svc3-specterlog/exploits/solver.py",
    "svc4": ROOT / "platform/challenges/svc4-nanofleet/exploits/solver.py",
    "svc5": ROOT / "platform/challenges/svc5-policyforge/exploits/solver.py",
}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run team1 reference attacks against all team2 services and submit recovered flags."
    )
    p.add_argument("--control", default="http://127.0.0.1:8088")
    p.add_argument("--attacker", default="team1")
    p.add_argument("--target", default="team2")
    p.add_argument("--team-token", default="submit-team1")
    p.add_argument("--services", default="svc1,svc2,svc3,svc4,svc5")
    p.add_argument("--source-ip", default="team1-nat")
    p.add_argument("--target-host-template", default="{target}-{service}:8080")
    p.add_argument("--poll-seconds", type=float, default=3.0)
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--once", action="store_true")
    p.add_argument("--max-ticks", type=int, default=0)
    p.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--no-docker", action="store_true")
    p.add_argument("--docker-image", default="kossim-control-api")
    p.add_argument("--docker-network", default="kossim_ctf_net")
    return p


def docker_reexec(args: argparse.Namespace) -> int | None:
    if args.inside or args.no_docker or os.path.exists("/.dockerenv"):
        return None
    if not shutil.which("docker"):
        return None
    inner_control = "http://control-api:8000"
    cmd = [
        "docker",
        "run",
        "--rm",
        "--network",
        args.docker_network,
        "-v",
        f"{ROOT}:/work",
        "-w",
        "/work",
        args.docker_image,
        "python",
        "scripts/team1_hack_team2.py",
        "--inside",
        "--control",
        inner_control,
        "--attacker",
        args.attacker,
        "--target",
        args.target,
        "--team-token",
        args.team_token,
        "--services",
        args.services,
        "--source-ip",
        args.source_ip,
        "--target-host-template",
        args.target_host_template,
        "--poll-seconds",
        str(args.poll_seconds),
        "--timeout",
        str(args.timeout),
        "--max-ticks",
        str(args.max_ticks),
    ]
    if args.once:
        cmd.append("--once")
    return subprocess.call(cmd)


def get_json(url: str, timeout: float) -> dict[str, Any]:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def find_team_ip(feed: dict[str, Any], target: str) -> str:
    for team in feed.get("teams", []):
        if team.get("name") == target:
            return str(team.get("ip") or team.get("nat_alias") or target)
    raise RuntimeError(f"target team not found in feed: {target}")


def target_base(template: str, target: str, service: str) -> str:
    host = template.format(target=target, service=service)
    if host.startswith("http://") or host.startswith("https://"):
        return host.rstrip("/")
    return f"http://{host}".rstrip("/")


def run_solver(
    *,
    service: str,
    control: str,
    feed_target_ip: str,
    base: str,
    tick: int,
    timeout: float,
    flag_re: re.Pattern[str],
) -> list[str]:
    solver = SOLVERS[service]
    cmd = [
        sys.executable,
        str(solver),
        "--control",
        control,
        "--service",
        service,
        "--target-ip",
        feed_target_ip,
        "--target-base",
        base,
        "--tick",
        str(tick),
    ]
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or f"{service} solver failed").strip())
    return list(dict.fromkeys(flag_re.findall(proc.stdout)))


def submit(control: str, token: str, flags: list[str], source_ip: str, timeout: float) -> dict[str, Any]:
    if not flags:
        return {"accepted_count": 0, "results": []}
    headers = {"X-Source-IP": source_ip} if source_ip else {}
    response = requests.post(
        f"{control}/api/v1/flags/submit",
        json={"team_token": token, "flags": flags},
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def attack_tick(args: argparse.Namespace, tick_seen: set[int], submitted: set[str]) -> int:
    attack = get_json(f"{args.control}/api/attack.json", args.timeout)
    teams = get_json(f"{args.control}/api/teams.json", args.timeout)
    tick = int(attack.get("current_tick") or 1)
    if tick in tick_seen:
        return tick
    feed_target_ip = find_team_ip(teams, args.target)
    flag_re = re.compile(attack.get("flag_regex", r"FLAG\{[A-Za-z0-9_\-=]{32,36}\}"))
    services = [svc.strip() for svc in args.services.split(",") if svc.strip()]

    found_by_service: dict[str, list[str]] = {}
    all_flags: list[str] = []
    for service in services:
        base = target_base(args.target_host_template, args.target, service)
        try:
            flags = run_solver(
                service=service,
                control=args.control,
                feed_target_ip=feed_target_ip,
                base=base,
                tick=tick,
                timeout=args.timeout,
                flag_re=flag_re,
            )
        except Exception as exc:
            print(f"[tick {tick}] {service}: ERROR {exc}", flush=True)
            flags = []
        fresh = [flag for flag in flags if flag not in submitted]
        found_by_service[service] = fresh
        all_flags.extend(fresh)

    all_flags = list(dict.fromkeys(all_flags))
    result = submit(args.control, args.team_token, all_flags, args.source_ip, args.timeout)
    for flag in all_flags:
        submitted.add(flag)
    tick_seen.add(tick)

    statuses: dict[str, int] = {}
    for row in result.get("results", []):
        statuses[row.get("status", "unknown")] = statuses.get(row.get("status", "unknown"), 0) + 1
    counts = ", ".join(f"{svc}={len(flags)}" for svc, flags in found_by_service.items())
    print(
        f"[tick {tick}] found {len(all_flags)} flags ({counts}); "
        f"accepted={result.get('accepted_count', 0)} statuses={json.dumps(statuses, sort_keys=True)}",
        flush=True,
    )
    return tick


def main() -> int:
    args = parser().parse_args()
    args.control = args.control.rstrip("/")
    rc = docker_reexec(args)
    if rc is not None:
        return rc

    tick_seen: set[int] = set()
    submitted: set[str] = set()
    completed = 0
    print(
        f"attacker={args.attacker} target={args.target} control={args.control} services={args.services}",
        flush=True,
    )
    while True:
        try:
            before = len(tick_seen)
            attack_tick(args, tick_seen, submitted)
            if len(tick_seen) > before:
                completed += 1
        except KeyboardInterrupt:
            print("stopped", flush=True)
            return 130
        except Exception as exc:
            print(f"loop error: {exc}", flush=True)

        if args.once or (args.max_ticks and completed >= args.max_ticks):
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
