"""Positive attack/defense scoring for the local control plane.

The cumulative per-service score is:

    service_score = off_points + def_points
    service_total = service_score * sla_points

ATK and DEF are monotonic: later submissions never reduce already-awarded
points. ``sla_points`` is a running service-health multiplier, not an additive
point bucket.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


BASE_ATTACK_POINTS: float = 10.0
BASE_DEFENSE_POINTS: float = 5.0


@dataclass
class TeamPointsLite:
    team_id: int
    service_id: int
    tick: int
    off_points: float = 0.0
    def_points: float = 0.0
    sla_points: float = 0.0
    sla_delta: float = 0.0
    flag_captured_count: int = 0
    flag_stolen_count: int = 0


@dataclass
class ServiceSpec:
    id: int
    name: str
    num_payloads: int = 1
    flags_per_tick: int = 1


@dataclass
class StolenFlag:
    """One submission event during the tick being scored."""

    target_team_id: int
    submitter_team_id: int
    service_id: int
    tick_issued: int
    payload: int
    flag: str
    num_previous_submissions: int
    num_submissions: int
    previous_submitter_ids: Sequence[int]


CheckerResults = Mapping[
    int,
    Mapping[Tuple[int, int], Tuple[str, Optional[Mapping[str, str]]]],
]
PrevAttacking = Mapping[Tuple[int, int, int], Mapping[int, Set[int]]]
NumActive = Mapping[int, Set[int]]


def _flagstore_count(service: ServiceSpec) -> float:
    return max(float(service.flags_per_tick or service.num_payloads or 1), 1.0)


def attack_points(service: ServiceSpec) -> float:
    return BASE_ATTACK_POINTS / _flagstore_count(service)


def defense_points(service: ServiceSpec) -> float:
    return BASE_DEFENSE_POINTS * _flagstore_count(service)


def service_health(
    *,
    current_tick: int,
    service: ServiceSpec,
    retention: int,
    status: str,
    getflags: Optional[Mapping[str, str]],
) -> float:
    if status == "SUCCESS":
        return 1.0
    if status != "RECOVERING" or getflags is None:
        return 0.0

    stores = max(int(service.num_payloads or service.flags_per_tick or 1), 1)
    expected = retention * stores
    ok = 0
    for related_tick in range(current_tick - retention + 1, current_tick + 1):
        for store_id in range(stores):
            ok += getflags.get(f"{related_tick}_{store_id}") == "OK"
    return ok / max(expected, 1)


def _valid_flag_submission(
    *,
    current_tick: int,
    retention: int,
    nop_team_id: Optional[int],
    flag: StolenFlag,
) -> bool:
    if nop_team_id is not None and (
        flag.target_team_id == nop_team_id or flag.submitter_team_id == nop_team_id
    ):
        return False
    if flag.submitter_team_id == flag.target_team_id:
        return False
    if flag.tick_issued <= current_tick - retention:
        return False
    return True


def calculate_scoring_for_tick(
    *,
    current_tick: int,
    services: Sequence[ServiceSpec],
    team_ids: Sequence[int],
    nop_team_id: Optional[int],
    retention: int,
    checker_results: CheckerResults,
    last_tick_points: Mapping[Tuple[int, int], TeamPointsLite],
    prev_attacking: PrevAttacking,
    num_active: NumActive,
    flags: Iterable[StolenFlag],
) -> Tuple[Dict[Tuple[int, int], TeamPointsLite], Dict[Tuple[int, int, int], Dict[int, Set[int]]]]:
    """Return (new_tick_points, attacking_state_for_this_tick).

    The attack state is returned for compatibility with the rotator. The
    positive scoring formula no longer needs it for point calculation.
    """
    services_by_id = {service.id: service for service in services}
    new_tick_points: Dict[Tuple[int, int], TeamPointsLite] = {}
    for team_id in team_ids:
        for service in services:
            new_tick_points[(team_id, service.id)] = TeamPointsLite(
                team_id=team_id,
                service_id=service.id,
                tick=current_tick,
            )

    service_health_by_pair: Dict[Tuple[int, int], float] = {}
    for (team_id, service_id), tp in new_tick_points.items():
        status, getflags = checker_results.get(current_tick, {}).get(
            (team_id, service_id),
            ("OFFLINE", None),
        )
        health = service_health(
            current_tick=current_tick,
            service=services_by_id[service_id],
            retention=retention,
            status=status,
            getflags=getflags,
        )
        service_health_by_pair[(team_id, service_id)] = health
        tp.sla_delta = health

    hacked_services: Set[Tuple[int, int]] = set()
    stolen_flags_seen: Set[Tuple[str, int, int, int]] = set()
    new_attacking: Dict[Tuple[int, int, int], Dict[int, Set[int]]] = {}

    for flag in flags:
        if not _valid_flag_submission(
            current_tick=current_tick,
            retention=retention,
            nop_team_id=nop_team_id,
            flag=flag,
        ):
            continue
        service = services_by_id.get(flag.service_id)
        attacker = new_tick_points.get((flag.submitter_team_id, flag.service_id))
        victim = new_tick_points.get((flag.target_team_id, flag.service_id))
        if service is None or attacker is None or victim is None:
            continue

        hacked_services.add((flag.target_team_id, flag.service_id))
        attacker.flag_captured_count += 1
        attacker.off_points += attack_points(service)

        flag_key = (flag.tick_issued, flag.service_id, flag.payload)
        new_attacking.setdefault(flag_key, {}).setdefault(flag.submitter_team_id, set()).add(
            flag.target_team_id
        )

        seen_key = (flag.flag, flag.tick_issued, flag.service_id, flag.payload)
        if seen_key not in stolen_flags_seen:
            stolen_flags_seen.add(seen_key)
            if flag.num_previous_submissions == 0:
                victim.flag_stolen_count += 1

    for (team_id, service_id), tp in new_tick_points.items():
        if nop_team_id is not None and team_id == nop_team_id:
            continue
        if (team_id, service_id) in hacked_services:
            continue
        if service_health_by_pair[(team_id, service_id)] <= 0:
            continue
        tp.def_points += defense_points(services_by_id[service_id])

    for (team_id, service_id), tp in new_tick_points.items():
        prev = last_tick_points.get((team_id, service_id))
        if prev is not None:
            tp.off_points += prev.off_points
            tp.def_points += prev.def_points
            tp.sla_points = (
                (prev.sla_points * (current_tick - 1)) + tp.sla_delta
            ) / current_tick
            tp.flag_captured_count += prev.flag_captured_count
            tp.flag_stolen_count += prev.flag_stolen_count
        else:
            tp.sla_points = tp.sla_delta / max(current_tick, 1)

    cumulative_attacking: Dict[Tuple[int, int, int], Dict[int, Set[int]]] = {}
    for flag_key, mapping in prev_attacking.items():
        cumulative_attacking[flag_key] = {
            attacker: set(victims) for attacker, victims in mapping.items()
        }
    for flag_key, mapping in new_attacking.items():
        bucket = cumulative_attacking.setdefault(flag_key, {})
        for attacker, victims in mapping.items():
            bucket.setdefault(attacker, set()).update(victims)

    return new_tick_points, cumulative_attacking
