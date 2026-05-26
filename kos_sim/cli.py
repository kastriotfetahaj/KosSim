from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from typing import Any, Dict

from .scenarios import SCENARIO_BUILDERS
from .simulator import AttackDefenseSimulator


def _to_dict(report: Any) -> Dict[str, Any]:
    payload = asdict(report)
    for round_payload in payload["rounds"]:
        round_payload["index"] = int(round_payload["index"])
    return payload


def _format_text(report_dict: Dict[str, Any]) -> str:
    lines = []
    lines.append(f"scenario: {report_dict['scenario_name']}")
    lines.append(f"objective_target: {report_dict['objective_target']}")
    lines.append(f"objective_reached: {report_dict['objective_reached']}")
    lines.append(f"winner: {report_dict['winner']}")
    lines.append(
        f"scores: attacker={report_dict['attacker_score']} defender={report_dict['defender_score']}"
    )
    lines.append(f"compromised_assets: {', '.join(report_dict['compromised_assets']) or 'none'}")
    lines.append("rounds:")
    for round_data in report_dict["rounds"]:
        lines.append(f"  - round {round_data['index']}:")
        lines.append(f"    defenses: {', '.join(round_data['defenses_applied']) or 'none'}")
        lines.append(f"    attacks: {', '.join(round_data['attack_events']) or 'none'}")
    return "\n".join(lines)


def run_scenario(name: str) -> Dict[str, Any]:
    builder = SCENARIO_BUILDERS.get(name)
    if builder is None:
        known = ", ".join(sorted(SCENARIO_BUILDERS.keys()))
        raise ValueError(f"Unknown scenario '{name}'. Available: {known}")
    simulator = AttackDefenseSimulator(builder())
    return _to_dict(simulator.run())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kos_sim", description="Attack/defense simulation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_cmd = subparsers.add_parser("run", help="Run a built-in scenario")
    run_cmd.add_argument("--scenario", required=True, help="Scenario name")
    run_cmd.add_argument(
        "--format",
        default="text",
        choices=["text", "json"],
        help="Output format",
    )

    subparsers.add_parser("list-scenarios", help="List available scenarios")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "list-scenarios":
        for name in sorted(SCENARIO_BUILDERS.keys()):
            print(name)
        return 0

    if args.command == "run":
        try:
            report = run_scenario(args.scenario)
        except ValueError as exc:
            print(str(exc))
            return 2

        if args.format == "json":
            print(json.dumps(report, indent=2))
        else:
            print(_format_text(report))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

