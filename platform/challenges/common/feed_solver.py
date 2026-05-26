from __future__ import annotations

import argparse
import json
from typing import Any

import requests


def parse_args(service: str, default_base: str = "http://127.0.0.1:8080") -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("base", nargs="?", default=None)
    parser.add_argument("mode", nargs="?", default="all")
    parser.add_argument("--control", default=None)
    parser.add_argument("--service", default=service)
    parser.add_argument("--target-ip", default=None)
    parser.add_argument("--target-base", default=None)
    parser.add_argument("--tick", default=None)
    args = parser.parse_args()
    if args.control:
        args.control = args.control.rstrip("/")
    if args.base is None:
        args.base = default_base
    args.base = args.base.rstrip("/")
    if args.target_base:
        args.target_base = args.target_base.rstrip("/")
    return args


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _decode(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return json.loads(value)
    if isinstance(value, dict):
        return value
    raise ValueError("unsupported flag id")


def service_base(host: str) -> str:
    if host.startswith("http://") or host.startswith("https://"):
        return host.rstrip("/")
    if ":" in host:
        return f"http://{host}".rstrip("/")
    return f"http://{host}:8080"


def from_feeds(args: argparse.Namespace) -> tuple[str, list[dict[str, Any]]]:
    if not args.control:
        return args.base, []
    attack = requests.get(f"{args.control}/api/attack.json", timeout=5).json()
    teams = requests.get(f"{args.control}/api/teams.json", timeout=5).json().get("teams", [])
    service = args.service
    by_service = attack.get("flag_ids", {}).get(service, {})
    if not by_service:
        raise RuntimeError(f"no flag ids for {service}")
    target_ip = args.target_ip
    if not target_ip:
        team_ips = [str(t.get("ip")) for t in teams if t.get("ip")]
        target_ip = next((ip for ip in team_ips if ip in by_service), None)
    if not target_ip:
        target_ip = next(iter(by_service))
    ticks = by_service[target_ip]
    tick = str(args.tick or attack.get("current_tick") or max(ticks, key=lambda x: int(x)))
    raw_infos = _as_list(ticks.get(tick))
    if not raw_infos:
        tick = max(ticks, key=lambda x: int(x))
        raw_infos = _as_list(ticks[tick])
    return args.target_base or service_base(target_ip), [_decode(item) for item in raw_infos]
