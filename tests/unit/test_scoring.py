"""Tests for the positive attack/defense scoring engine."""

from __future__ import annotations

from collections import defaultdict

import pytest

from ksapp.scoring import (
    BASE_ATTACK_POINTS,
    BASE_DEFENSE_POINTS,
    ServiceSpec,
    StolenFlag,
    TeamPointsLite,
    attack_points,
    calculate_scoring_for_tick,
    defense_points,
    service_health,
)


SVC = ServiceSpec(id=1, name="svc1", num_payloads=1, flags_per_tick=1)


def _flag(
    *,
    submitter: int,
    target: int,
    submitted_tick: int,
    issued_tick: int,
    payload: int = 0,
    service_id: int = 1,
    previous: int = 0,
) -> StolenFlag:
    return StolenFlag(
        target_team_id=target,
        submitter_team_id=submitter,
        service_id=service_id,
        tick_issued=issued_tick,
        payload=payload,
        flag=f"FLAG-{target}-{service_id}-{issued_tick}-{payload}",
        num_previous_submissions=previous,
        num_submissions=1,
        previous_submitter_ids=[],
    )


def _score_one_tick(
    *,
    tick: int,
    teams: list[int],
    checker_results,
    last=None,
    flags=None,
    nop_team_id=None,
    retention=5,
):
    return calculate_scoring_for_tick(
        current_tick=tick,
        services=[SVC],
        team_ids=teams,
        nop_team_id=nop_team_id,
        retention=retention,
        checker_results=checker_results,
        last_tick_points=last or {},
        prev_attacking={},
        num_active={},
        flags=flags or [],
    )[0]


def test_attack_and_defense_constants_scale_with_flagstores():
    svc = ServiceSpec(id=1, name="multi", num_payloads=2, flags_per_tick=2)

    assert attack_points(SVC) == BASE_ATTACK_POINTS
    assert defense_points(SVC) == BASE_DEFENSE_POINTS
    assert attack_points(svc) == BASE_ATTACK_POINTS / 2
    assert defense_points(svc) == BASE_DEFENSE_POINTS * 2


def test_service_health_success_offline_and_recovering():
    assert (
        service_health(
            current_tick=3,
            service=SVC,
            retention=5,
            status="SUCCESS",
            getflags=None,
        )
        == 1.0
    )
    assert (
        service_health(
            current_tick=3,
            service=SVC,
            retention=5,
            status="OFFLINE",
            getflags=None,
        )
        == 0.0
    )
    assert service_health(
        current_tick=5,
        service=SVC,
        retention=5,
        status="RECOVERING",
        getflags={"1_0": "OK", "3_0": "OK", "5_0": "OK"},
    ) == pytest.approx(3 / 5)


def test_empty_inputs_yield_zero_points_for_every_pair():
    pts = _score_one_tick(tick=1, teams=[1, 2, 3], checker_results={})

    for tp in pts.values():
        assert tp.off_points == 0.0
        assert tp.def_points == 0.0
        assert tp.sla_points == 0.0
        assert tp.sla_delta == 0.0
        assert tp.flag_captured_count == 0
        assert tp.flag_stolen_count == 0


def test_success_awards_defense_and_full_sla_when_not_hacked():
    pts = _score_one_tick(
        tick=1,
        teams=[1],
        checker_results={1: {(1, 1): ("SUCCESS", None)}},
    )

    assert pts[(1, 1)].off_points == 0.0
    assert pts[(1, 1)].def_points == BASE_DEFENSE_POINTS
    assert pts[(1, 1)].sla_delta == 1.0
    assert pts[(1, 1)].sla_points == 1.0


def test_attack_gives_fixed_positive_points_and_blocks_victim_defense():
    flag = _flag(submitter=1, target=2, submitted_tick=1, issued_tick=1)
    pts = _score_one_tick(
        tick=1,
        teams=[1, 2],
        checker_results={
            1: {(1, 1): ("SUCCESS", None), (2, 1): ("SUCCESS", None)}
        },
        flags=[flag],
    )

    assert pts[(1, 1)].off_points == BASE_ATTACK_POINTS
    assert pts[(1, 1)].def_points == BASE_DEFENSE_POINTS
    assert pts[(1, 1)].flag_captured_count == 1
    assert pts[(2, 1)].off_points == 0.0
    assert pts[(2, 1)].def_points == 0.0
    assert pts[(2, 1)].flag_stolen_count == 1


def test_multiple_submitters_keep_same_positive_value_without_clawback():
    flags = [
        _flag(submitter=1, target=3, submitted_tick=1, issued_tick=1),
        _flag(submitter=2, target=3, submitted_tick=1, issued_tick=1),
    ]
    pts = _score_one_tick(
        tick=1,
        teams=[1, 2, 3],
        checker_results={
            1: {
                (1, 1): ("SUCCESS", None),
                (2, 1): ("SUCCESS", None),
                (3, 1): ("SUCCESS", None),
            }
        },
        flags=flags,
    )

    assert pts[(1, 1)].off_points == BASE_ATTACK_POINTS
    assert pts[(2, 1)].off_points == BASE_ATTACK_POINTS
    assert pts[(3, 1)].flag_stolen_count == 1


def test_nop_self_and_expired_flags_are_ignored():
    pts = _score_one_tick(
        tick=10,
        teams=[1, 2, 99],
        nop_team_id=99,
        checker_results={
            10: {
                (1, 1): ("SUCCESS", None),
                (2, 1): ("SUCCESS", None),
                (99, 1): ("SUCCESS", None),
            }
        },
        flags=[
            _flag(submitter=1, target=99, submitted_tick=10, issued_tick=10),
            _flag(submitter=99, target=1, submitted_tick=10, issued_tick=10),
            _flag(submitter=2, target=2, submitted_tick=10, issued_tick=10),
            _flag(submitter=1, target=2, submitted_tick=10, issued_tick=5),
        ],
    )

    assert pts[(1, 1)].off_points == 0.0
    assert pts[(2, 1)].off_points == 0.0
    assert pts[(2, 1)].flag_stolen_count == 0
    assert pts[(99, 1)].def_points == 0.0


def test_previous_tick_points_accumulate_and_sla_is_running_average():
    last = {
        (1, 1): TeamPointsLite(
            team_id=1,
            service_id=1,
            tick=1,
            off_points=5.0,
            def_points=2.0,
            sla_points=1.0,
            flag_captured_count=3,
            flag_stolen_count=1,
        )
    }
    pts = _score_one_tick(
        tick=2,
        teams=[1],
        checker_results={2: {(1, 1): ("OFFLINE", None)}},
        last=last,
    )

    tp = pts[(1, 1)]
    assert tp.off_points == 5.0
    assert tp.def_points == 2.0
    assert tp.sla_delta == 0.0
    assert tp.sla_points == 0.5
    assert tp.flag_captured_count == 3
    assert tp.flag_stolen_count == 1


def test_scoring_10_teams_10_rounds():
    teams = list(range(1, 11))
    flags_by_tick = defaultdict(list)
    for submitted_tick, flag in [
        (1, _flag(submitter=2, target=3, submitted_tick=1, issued_tick=1)),
        (1, _flag(submitter=4, target=3, submitted_tick=1, issued_tick=1)),
        (2, _flag(submitter=2, target=4, submitted_tick=2, issued_tick=2)),
        (5, _flag(submitter=6, target=7, submitted_tick=5, issued_tick=3)),
        (8, _flag(submitter=8, target=9, submitted_tick=8, issued_tick=4)),
        (10, _flag(submitter=2, target=10, submitted_tick=10, issued_tick=5)),
    ]:
        flags_by_tick[submitted_tick].append(flag)

    last = {}
    all_points = {}
    for tick in range(1, 11):
        statuses = {
            (team_id, 1): ("SUCCESS", None)
            for team_id in teams
        }
        if tick == 4:
            statuses[(5, 1)] = ("OFFLINE", None)
        points = _score_one_tick(
            tick=tick,
            teams=teams,
            checker_results={tick: statuses},
            last=last,
            flags=flags_by_tick[tick],
            retention=5,
        )
        for result in points.values():
            assert result.off_points >= 0.0
            assert result.def_points >= 0.0
            assert result.sla_points >= 0.0
        all_points[tick] = points
        last = points

    final = all_points[10]
    totals = {
        team_id: final[(team_id, 1)].off_points
        + final[(team_id, 1)].def_points
        for team_id in teams
    }
    ranked = {
        team_id: totals[team_id] * final[(team_id, 1)].sla_points
        for team_id in teams
    }

    assert ranked[1] == pytest.approx(50.0)
    assert ranked[2] == pytest.approx(70.0)
    assert ranked[3] == pytest.approx(45.0)
    assert ranked[4] == pytest.approx(55.0)
    assert ranked[5] == pytest.approx(40.5)
    assert ranked[6] == pytest.approx(60.0)
    assert ranked[7] == pytest.approx(45.0)
    assert ranked[8] == pytest.approx(60.0)
    assert ranked[9] == pytest.approx(45.0)
    assert ranked[10] == pytest.approx(50.0)


def test_scoring_10_teams_10_rounds_5_services_2_flagstores():
    services = [
        ServiceSpec(id=sid, name=f"svc{sid}", num_payloads=2, flags_per_tick=2)
        for sid in range(1, 6)
    ]
    teams = list(range(1, 11))
    flags_by_tick = defaultdict(list)
    schedule = [
        (1, _flag(submitter=1, target=2, submitted_tick=1, issued_tick=1, service_id=1, payload=0)),
        (1, _flag(submitter=3, target=2, submitted_tick=1, issued_tick=1, service_id=1, payload=1)),
        (2, _flag(submitter=4, target=5, submitted_tick=2, issued_tick=2, service_id=2, payload=0)),
        (4, _flag(submitter=6, target=7, submitted_tick=4, issued_tick=3, service_id=3, payload=1)),
        (7, _flag(submitter=8, target=9, submitted_tick=7, issued_tick=5, service_id=4, payload=0)),
        (10, _flag(submitter=10, target=1, submitted_tick=10, issued_tick=8, service_id=5, payload=1)),
    ]
    for tick, flag in schedule:
        flags_by_tick[tick].append(flag)

    last = {}
    final = {}
    for tick in range(1, 11):
        statuses = {
            (team_id, service.id): ("SUCCESS", None)
            for team_id in teams
            for service in services
        }
        if tick == 3:
            statuses[(4, 2)] = ("OFFLINE", None)
        if tick == 6:
            statuses[(9, 4)] = ("RECOVERING", {"2_0": "OK", "4_1": "OK", "6_0": "OK"})

        points, _ = calculate_scoring_for_tick(
            current_tick=tick,
            services=services,
            team_ids=teams,
            nop_team_id=None,
            retention=5,
            checker_results={tick: statuses},
            last_tick_points=last,
            prev_attacking={},
            num_active={},
            flags=flags_by_tick[tick],
        )

        for tp in points.values():
            assert tp.off_points >= 0
            assert tp.def_points >= 0
            assert tp.sla_points >= 0
            service_total = (tp.off_points + tp.def_points) * tp.sla_points
            assert service_total >= 0
        if tick == 1:
            assert points[(2, 1)].def_points == 0
            assert points[(1, 1)].off_points == pytest.approx(BASE_ATTACK_POINTS / 2)
            assert points[(3, 1)].off_points == pytest.approx(BASE_ATTACK_POINTS / 2)
        if tick == 3:
            assert points[(4, 2)].sla_delta == 0
        final = points
        last = points

    team_totals = defaultdict(float)
    for (team_id, _service_id), tp in final.items():
        team_totals[team_id] += (tp.off_points + tp.def_points) * tp.sla_points

    assert len(team_totals) == 10
    assert team_totals[1] > 0
    assert team_totals[2] < team_totals[3]
