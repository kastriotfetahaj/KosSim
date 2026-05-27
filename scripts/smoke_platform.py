#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "docker-compose.smoke.generated.yml"


def run(cmd: list[str], *, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, env=env, check=check, text=True, capture_output=True)


def generate(team_count: int) -> str:
    run([sys.executable, "scripts/generate_compose.py", "--team-count", str(team_count), "--output", str(GENERATED)])
    return GENERATED.read_text()


def static_smoke(team_count: int) -> None:
    text = generate(team_count)
    expected_team_services = team_count * 5
    actual_team_services = sum(
        1 for line in text.splitlines() if line.startswith("  team") and "-svc" in line and line.endswith(":")
    )
    if actual_team_services != expected_team_services:
        raise SystemExit(f"expected {expected_team_services} team services, found {actual_team_services}")
    for path in (
        "/var/lib/ledgerforge",
        "/var/lib/vaultgrid",
        "/var/lib/specterlog",
        "/var/lib/nanofleet",
        "/var/lib/policyforge",
    ):
        if path not in text:
            raise SystemExit(f"generated compose missing {path}")
    run(["docker", "compose", "--env-file", ".env.example", "-f", str(GENERATED), "config"])
    print(json.dumps({"ok": True, "mode": "static", "team_services": actual_team_services, "compose": str(GENERATED)}))


def http_json(url: str, timeout: float = 3.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode())


def wait_for(url: str, timeout: int) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if 200 <= response.status < 500:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(2)
    raise SystemExit(f"timed out waiting for {url}")


def docker_smoke(team_count: int, timeout: int, keep: bool) -> None:
    generate(team_count)
    cmd = ["docker", "compose", "--env-file", ".env.example", "-f", str(GENERATED)]
    try:
        subprocess.run([*cmd, "down", "-v", "--remove-orphans"], cwd=ROOT, check=False)
        subprocess.run([*cmd, "up", "-d", "--build"], cwd=ROOT, check=True)
        wait_for("http://127.0.0.1:8088/health", timeout)
        scoreboard = http_json("http://127.0.0.1:8088/api/v1/scoreboard")
        if len(scoreboard.get("rows", [])) != team_count:
            raise SystemExit("scoreboard did not return expected teams")
        print(json.dumps({"ok": True, "mode": "docker", "teams": len(scoreboard.get("rows", []))}))
    finally:
        if not keep:
            subprocess.run([*cmd, "down", "-v", "--remove-orphans"], cwd=ROOT, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-check generated KosSim platform topology.")
    parser.add_argument("--team-count", type=int, default=2)
    parser.add_argument("--docker", action="store_true", help="boot the generated stack and check the scoreboard")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--keep", action="store_true", help="keep generated compose and docker stack")
    args = parser.parse_args()

    try:
        if args.docker:
            docker_smoke(args.team_count, args.timeout, args.keep)
        else:
            static_smoke(args.team_count)
    finally:
        if not args.keep and GENERATED.exists():
            GENERATED.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
