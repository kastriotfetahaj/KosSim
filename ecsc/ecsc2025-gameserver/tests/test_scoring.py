import json
import os
import time
import unittest
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, List, Tuple

from controlserver.models import (
    CheckerResult,
    Service,
    SubmittedFlag,
    Team,
    TeamPoints,
    TeamRanking,
    db_session,
    db_session_2,
)
from controlserver.scoring.algorithms.algorithm import ScoreTickAlgorithmAtklab
from controlserver.scoring.scoreboard import Scoreboard
from controlserver.scoring.scoring import ScoringCalculation
from saarctf_commons import config
from tests.utils.base_cases import DatabaseTestCase
from tests.utils.scriptrunner import ScriptRunner
from controlserver.timer import CTFState, init_mock_timer


class ScoringTestCase(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.config = config.ScoringConfig.from_dict(config.config.SCORING.to_dict())

    def save_checker_results(
        self,
        results: List[Tuple[int, List[str]]],
        team_ids: list[int] | None = None,
        service_ids: list[int] | None = None,
    ) -> None:
        session = db_session()
        if team_ids is None:
            team_ids = [team_id for (team_id,) in session.query(Team.id).order_by(Team.id)]
        if service_ids is None:
            service_ids = [
                service_id
                for (service_id,) in session.query(Service.id).order_by(Service.id)
            ]
        for tick, states in results:
            self.assertEqual(len(states), len(team_ids) * len(service_ids))
            for team_index, team_id in enumerate(team_ids):
                for service_index, service_id in enumerate(service_ids):
                    status = states[team_index * len(service_ids) + service_index]
                    self.assertIn(status, CheckerResult.states)
                    session.add(
                        CheckerResult(
                            team_id=team_id,
                            service_id=service_id,
                            tick=tick,
                            status=status,
                            celery_id="",
                        )
                    )
        session.commit()

    def save_stolen_flags(
        self, service_id: int, flags: List[Tuple[int, int, int, int, int]]
    ) -> None:
        session = db_session()
        for stolen_by, stolen_in, team_id, issued, payload in flags:
            session.add(
                SubmittedFlag(
                    service_id=service_id,
                    submitted_by=stolen_by,
                    tick_submitted=stolen_in,
                    team_id=team_id,
                    tick_issued=issued,
                    payload=payload,
                )
            )
            session.commit()
            time.sleep(0.002)

    def create_teams_and_services(self, team_count: int, service_count: int = 1) -> None:
        with db_session_2() as session:
            for team_id in range(1, team_count + 1):
                session.add(Team(id=team_id, name=f"Team{team_id}"))
            for service_id in range(1, service_count + 1):
                session.add(
                    Service(
                        id=service_id,
                        name=f"Service{service_id}",
                        checker_script="checker_runner.demo_checker:WorkingService",
                        checker_timeout=1,
                        num_payloads=1,
                        flags_per_tick=1,
                    )
                )
            session.commit()

    def test_empty_scratch(self) -> None:
        self.assertEqual(0, TeamPoints.query.count())
        self.demo_team_services()

    def test_scoring(self) -> None:
        self.demo_team_services()
        self._create_results()

        scoring = ScoringCalculation(self.config)
        for rn in range(1, 21):
            scoring.calculate_scoring_for_tick(rn)
            scoring.calculate_ranking_per_tick(rn)

        self.assert_scoring_matches_formula(20)

        first_blood_flags = [
            (1, 2, 8, 3, 8, 0),
            (2, 2, 20, 3, 10, 0),
            (3, 3, 15, 2, 15, 0),
            (3, 3, 15, 4, 15, 1),
        ]
        for flag in self.get_flags():
            key = (
                flag.service_id,
                flag.submitted_by,
                flag.tick_submitted,
                flag.team_id,
                flag.tick_issued,
                flag.payload,
            )
            should_be = key in first_blood_flags
            self.assertEqual(should_be, flag.is_firstblood, f"wrong: {key}")

    def test_scoring_10_teams_10_rounds(self) -> None:
        self.config.nop_team_id = 0
        self.config.flags_rounds_valid = 5
        self.create_teams_and_services(team_count=10, service_count=1)
        checker_results = [(tick, ["SUCCESS"] * 10) for tick in range(1, 11)]
        checker_results[3] = (4, ["SUCCESS"] * 4 + ["OFFLINE"] + ["SUCCESS"] * 5)
        self.save_checker_results(checker_results)
        self.save_stolen_flags(
            1,
            [
                (2, 1, 3, 1, 0),
                (4, 1, 3, 1, 0),
                (2, 2, 4, 2, 0),
                (6, 5, 7, 3, 0),
                (8, 8, 9, 4, 0),
                (2, 10, 10, 5, 0),  # expired, should not score
            ],
        )

        scoring = ScoringCalculation(self.config)
        for rn in range(1, 11):
            scoring.calculate_scoring_for_tick(rn)
            scoring.calculate_ranking_per_tick(rn)

        self.assert_scoring_matches_formula(10)
        rankings = self.get_rankings()
        self.assertAlmostEqual(rankings[1, 10].points, 50.0)
        self.assertAlmostEqual(rankings[2, 10].points, 70.0)
        self.assertAlmostEqual(rankings[3, 10].points, 45.0)
        self.assertAlmostEqual(rankings[4, 10].points, 55.0)
        self.assertAlmostEqual(rankings[5, 10].points, 40.5)
        self.assertAlmostEqual(rankings[6, 10].points, 60.0)
        self.assertAlmostEqual(rankings[7, 10].points, 45.0)
        self.assertAlmostEqual(rankings[8, 10].points, 60.0)
        self.assertAlmostEqual(rankings[9, 10].points, 45.0)
        self.assertAlmostEqual(rankings[10, 10].points, 50.0)

    def test_scoring_factors(self) -> None:
        self.config = config.ScoringConfig.from_dict(config.config.SCORING.to_dict())
        self.config.off_factor = 2.0
        self.config.def_factor = 3.5
        self.config.sla_factor = 0.8
        self.test_scoring()

    def _create_results(self):
        # mock checker results
        checker_results = [
            (1, ["SUCCESS", "SUCCESS", "SUCCESS"] * 4),
            (2, ["SUCCESS", "SUCCESS", "SUCCESS"] * 4),
            (3, ["SUCCESS", "SUCCESS", "OFFLINE"] * 4),  # Service 3 is broken for all
            (4, ["SUCCESS", "SUCCESS", "FLAGMISSING"] * 4),
            (5, ["SUCCESS", "SUCCESS", "MUMBLE"] * 4),
            (
                6,
                ["SUCCESS", "SUCCESS", "SUCCESS"] * 3
                + ["OFFLINE", "OFFLINE", "OFFLINE"],
            ),
            # team 4 is completely offline
        ]
        checker_results += [
            (i, ["SUCCESS", "SUCCESS", "SUCCESS"] * 4) for i in range(7, 21)
        ]  # rest is ok - up to tick 20
        self.save_checker_results(checker_results)
        # stolen flags: [stolen_by, stolen_in, team_id, issued, payload]
        self.save_stolen_flags(
            1,
            [
                (2, 8, 3, 8, 0),
                (2, 8, 4, 7, 0),
                (2, 8, 4, 8, 0),
                (2, 9, 3, 9, 0),
                (2, 9, 4, 9, 0),
                (2, 11, 3, 10, 0),
                (2, 11, 4, 10, 0),
                (2, 11, 3, 11, 0),
                (2, 11, 4, 11, 0),
                (3, 11, 4, 10, 0),
                (3, 11, 4, 11, 0),  # 2 and 3 steal the same flags
                (2, 15, 4, 15, 0),
                (3, 17, 4, 15, 0),  # two team steal the same flag in a different tick
            ],
        )
        self.save_stolen_flags(
            2, [(2, 20, 3, 10, 0)]
        )  # submit flag that is just about to expire
        self.save_stolen_flags(
            3, [(3, 15, 2, 15, 0), (3, 15, 4, 15, 0), (3, 15, 4, 15, 1)]
        )  # submit 1 flag from #2 and 2 flags from #4

    def test_scoring_double_submit(self) -> None:
        """
        This scenario caused a bug once: first 1 team submits, then more teams
        submit the same flag in the next tick.
        :return:
        """
        self.config.nop_team_id = 0
        self.demo_team_services()
        checker_results = [
            (i, ["SUCCESS", "SUCCESS", "SUCCESS"] * 4) for i in range(1, 4)
        ]
        self.save_checker_results(checker_results)
        self.save_stolen_flags(
            1,
            [
                (2, 2, 1, 1, 0),  # first team 2 steals the flag
                (3, 3, 1, 1, 0),
                (4, 3, 1, 1, 0),  # then team 3+4 steal the flag
            ],
        )

        scoring = ScoringCalculation(self.config)
        for rn in range(1, 4):
            scoring.calculate_scoring_for_tick(rn)
            scoring.calculate_ranking_per_tick(rn)

        self.assert_scoring_matches_formula(3)
        results = self.get_results()
        self.assertAlmostEqual(results[1, 2, 2].off_points, self.flag_formula(1))
        self.assertAlmostEqual(results[1, 2, 3].off_points, self.flag_formula(1))
        self.assertAlmostEqual(results[1, 3, 3].off_points, self.flag_formula(1))
        self.assertAlmostEqual(results[1, 4, 3].off_points, self.flag_formula(1))
        self.assertEqual(results[1, 1, 3].flag_stolen_count, 1)
        self.assertAlmostEqual(results[1, 1, 3].def_points, self.def_formula(1))

        first_blood_flags = [(1, 2, 2, 1, 1, 0)]
        for flag in self.get_flags():
            should_be = (
                flag.service_id,
                flag.submitted_by,
                flag.tick_submitted,
                flag.team_id,
                flag.tick_issued,
                flag.payload,
            ) in first_blood_flags
            self.assertEqual(should_be, flag.is_firstblood)

    def service_flag_count(self, service_id: int) -> float:
        service = Service.query.filter(Service.id == service_id).one()
        return max(float(service.flags_per_tick), 1.0)

    def flag_formula(self, service_id: int) -> float:
        return (
            ScoreTickAlgorithmAtklab.BASE_ATTACK_POINTS
            / self.service_flag_count(service_id)
            * self.config.off_factor
        )

    def sla_formula(self, service_id: int, health: float = 1.0) -> float:
        return health * self.config.sla_factor

    def def_formula(self, service_id: int) -> float:
        return (
            ScoreTickAlgorithmAtklab.BASE_DEFENSE_POINTS
            * self.service_flag_count(service_id)
            * self.config.def_factor
        )

    def checker_health(
        self,
        tick: int,
        service_id: int,
        status: str,
        getflags: dict[str, str] | None,
    ) -> float:
        if status == "SUCCESS":
            return 1.0
        if status != "RECOVERING" or getflags is None:
            return 0.0
        stores = max(int(self.service_flag_count(service_id)), 1)
        expected = self.config.flags_rounds_valid * stores
        ok = 0
        for related_tick in range(tick - self.config.flags_rounds_valid + 1, tick + 1):
            for flagstore_id in range(stores):
                ok += getflags.get(f"{related_tick}_{flagstore_id}") == "OK"
        return ok / max(expected, 1)

    def valid_for_scoring(self, flag: SubmittedFlag, tick: int) -> bool:
        if flag.team_id == self.config.nop_team_id:
            return False
        if flag.submitted_by == self.config.nop_team_id:
            return False
        if flag.submitted_by == flag.team_id:
            return False
        return flag.tick_issued > tick - self.config.flags_rounds_valid

    def assert_scoring_matches_formula(self, max_tick: int) -> None:
        results = self.get_results()
        rankings = self.get_rankings()
        team_ids = [team_id for (team_id,) in Team.query.order_by(Team.id).with_entities(Team.id)]
        service_ids = [
            service_id
            for (service_id,) in Service.query.order_by(Service.id).with_entities(Service.id)
        ]
        checker_results = {
            (cr.tick, cr.team_id, cr.service_id): (cr.status, cr.data)
            for cr in CheckerResult.query.all()
        }
        flags = self.get_flags()
        flags_by_tick: dict[int, list[SubmittedFlag]] = defaultdict(list)
        for flag in flags:
            flags_by_tick[flag.tick_submitted].append(flag)

        off_sum: dict[tuple[int, int], float] = defaultdict(float)
        def_sum: dict[tuple[int, int], float] = defaultdict(float)
        sla_sum: dict[tuple[int, int], float] = defaultdict(float)
        captured_sum: dict[tuple[int, int], int] = defaultdict(int)
        stolen_sum: dict[tuple[int, int], int] = defaultdict(int)

        for tick in range(1, max_tick + 1):
            previous_counts: dict[tuple[int, int, int, int], int] = defaultdict(int)
            for flag in flags:
                key = (flag.team_id, flag.service_id, flag.tick_issued, flag.payload)
                if (
                    tick - self.config.flags_rounds_valid - 2
                    <= flag.tick_submitted
                    < tick
                ):
                    previous_counts[key] += 1

            hacked_services: set[tuple[int, int]] = set()
            stolen_seen_this_tick: set[tuple[int, int, int, int]] = set()
            for flag in flags_by_tick[tick]:
                if not self.valid_for_scoring(flag, tick):
                    continue
                key = (flag.team_id, flag.service_id, flag.tick_issued, flag.payload)
                hacked_services.add((flag.team_id, flag.service_id))
                off_sum[(flag.submitted_by, flag.service_id)] += self.flag_formula(
                    flag.service_id
                )
                captured_sum[(flag.submitted_by, flag.service_id)] += 1
                if previous_counts[key] == 0 and key not in stolen_seen_this_tick:
                    stolen_sum[(flag.team_id, flag.service_id)] += 1
                    stolen_seen_this_tick.add(key)

            expected_rank_points: dict[int, float] = defaultdict(float)
            for team_id in team_ids:
                for service_id in service_ids:
                    status, getflags = checker_results.get(
                        (tick, team_id, service_id), ("REVOKED", None)
                    )
                    health = self.checker_health(tick, service_id, status, getflags)
                    sla_sum[(team_id, service_id)] += self.sla_formula(
                        service_id, health
                    )
                    if (
                        team_id != self.config.nop_team_id
                        and (team_id, service_id) not in hacked_services
                        and health > 0
                    ):
                        def_sum[(team_id, service_id)] += self.def_formula(service_id)

                    result = results[service_id, team_id, tick]
                    self.assertGreaterEqual(result.off_points, 0.0)
                    self.assertGreaterEqual(result.def_points, 0.0)
                    self.assertGreaterEqual(result.sla_points, 0.0)
                    self.assertEqual(
                        result.flag_captured_count, captured_sum[team_id, service_id]
                    )
                    self.assertEqual(
                        result.flag_stolen_count, stolen_sum[team_id, service_id]
                    )
                    self.assertAlmostEqual(
                        result.off_points, off_sum[team_id, service_id]
                    )
                    self.assertAlmostEqual(
                        result.def_points, def_sum[team_id, service_id]
                    )
                    self.assertAlmostEqual(
                        result.sla_points, sla_sum[team_id, service_id] / tick
                    )
                    expected_rank_points[team_id] += (
                        off_sum[team_id, service_id]
                        + def_sum[team_id, service_id]
                    ) * (sla_sum[team_id, service_id] / tick)

            for team_id, points in expected_rank_points.items():
                self.assertAlmostEqual(rankings[team_id, tick].points, points)

    def get_results(self) -> Dict[Tuple[int, int, int], TeamPoints]:
        # service, team, tick
        result = {}
        for tp in TeamPoints.query.all():
            result[(tp.service_id, tp.team_id, tp.tick)] = tp
        return result

    def get_rankings(self) -> Dict[Tuple[int, int], TeamRanking]:
        result = {}
        for tr in TeamRanking.query.all():
            result[(tr.team_id, tr.tick)] = tr
        return result

    def get_flags(self) -> list[SubmittedFlag]:
        with db_session_2() as session:
            return session.query(SubmittedFlag).all()

    def test_scoreboard(self) -> None:
        timer = init_mock_timer()
        self.demo_team_services()
        self._create_results()
        with TemporaryDirectory() as directory:
            base = Path(directory)
            config.current_config.PUBLIC_SCOREBOARD_PATH = base
            scoring = ScoringCalculation(self.config)
            scoreboard = Scoreboard(scoring, publish=False)
            (base / "api").mkdir(parents=True)
            scoreboard.prepared_static_files = True
            scoreboard.update_tick_info()
            scoreboard.create_scoreboard(-1, False, False)
            scoreboard.create_scoreboard(0, True, False)
            files = os.listdir(base / "api")
            for f in [
                "scoreboard_current.json",
                "scoreboard_round_-1.json",
                "scoreboard_round_0.json",
                "scoreboard_team_1.json",
                "scoreboard_team_2.json",
                "scoreboard_team_3.json",
                "scoreboard_team_4.json",
                "scoreboard_teams.json",
            ]:
                self.assertIn(f, files)

            for rn in range(1, 21):
                timer.current_tick = rn
                scoring.calculate_scoring_for_tick(rn)
                scoring.calculate_ranking_per_tick(rn)
                scoreboard.create_scoreboard(rn, True, True)
                self.assertTrue((base / "api" / f"scoreboard_round_{rn}.json").exists())

    def test_ctftime_export(self) -> None:
        timer = init_mock_timer()
        timer.state = CTFState.STOPPED
        timer.desired_state = CTFState.STOPPED
        timer.update_redis()
        self.demo_team_services()
        self._create_results()
        scoring = ScoringCalculation(self.config)
        for rn in range(1, 21):
            timer.current_tick = rn
            scoring.calculate_scoring_for_tick(rn)
            scoring.calculate_ranking_per_tick(rn)

        with TemporaryDirectory() as directory:
            result = ScriptRunner.run_script(
                "scripts/export_ctftime_scoreboard.py",
                [os.path.join(directory, "ctftime.json")],
            )
            ScriptRunner.assert_no_exception(result)
            with open(os.path.join(directory, "ctftime.json"), "r") as f:
                content = json.loads(f.read())
            self.assertEqual(
                {standing["team"] for standing in content["standings"]},
                {"Team2", "Team3", "Team4"},
            )
            self.assertEqual(
                [standing["pos"] for standing in content["standings"]],
                sorted(standing["pos"] for standing in content["standings"]),
            )
            self.assertTrue(
                all(standing["score"] > 0 for standing in content["standings"])
            )


if __name__ == "__main__":
    unittest.main()
