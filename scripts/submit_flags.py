#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

import requests


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Submit flags to KosSim control plane")
    parser.add_argument("--endpoint", required=True, help="Flag submit endpoint URL")
    parser.add_argument("--team-token", required=True, help="Team submit token")
    parser.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout in seconds")
    parser.add_argument("--flags", nargs="*", default=[], help="Flags inline")
    parser.add_argument("--flags-file", default="", help="Text file with one flag per line")
    parser.add_argument("--source-ip", default="", help="Optional explicit source IP header")
    return parser


def _load_flags(args: argparse.Namespace) -> List[str]:
    flags = [flag.strip() for flag in args.flags if flag.strip()]
    if args.flags_file:
        path = Path(args.flags_file)
        for line in path.read_text().splitlines():
            flag = line.strip()
            if flag:
                flags.append(flag)
    return flags


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    flags = _load_flags(args)
    if not flags:
        parser.error("Provide at least one flag using --flags or --flags-file")

    headers = {}
    if args.source_ip:
        headers["X-Source-IP"] = args.source_ip

    response = requests.post(
        args.endpoint,
        json={"team_token": args.team_token, "flags": flags},
        headers=headers,
        timeout=args.timeout,
    )
    print(json.dumps(response.json(), indent=2))
    return 0 if response.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
