from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Collection, Mapping, TypeAlias
from controlserver.logger import log
from controlserver.models import (
    Service,
    TeamPointsLite,
    SubmittedFlag,
    LogMessage,
)
from saarctf_commons.config import ScoringConfig


TeamServicePair: TypeAlias = tuple[int, int]
TickTeamPair: TypeAlias = tuple[int, int]
ServiceTickPair: TypeAlias = tuple[int, int]
ServicePayloadPair: TypeAlias = tuple[int, int]


class FlagSet:
    def __init__(self) -> None:
        self._set: set[tuple[int, int, int, int]] = (
            set()
        )  # service, team, tick_issued, payload

    def is_new(self, flag: SubmittedFlag) -> bool:
        """
        Return True if this flag was not seen by this set before.
        Submitter is ignored, thus similar to "flag string".
        """
        key = (flag.service_id, flag.team_id, flag.tick_issued, flag.payload)
        if key in self._set:
            return False
        self._set.add(key)
        return True


@dataclass(frozen=True)
class StolenFlag:
    flag: SubmittedFlag
    num_previous_submissions: int
    num_submissions: int
    previous_submitter_ids: Collection[int]



class ScoreTickAlgorithm(ABC):
    """
    Scoring algorithm interface, which also implements most of the boilerplate to get/set results.
    """

    def __init__(
        self, config: ScoringConfig, team_ids: list[int], services: list[Service]
    ) -> None:
        self.config = config
        self.team_ids = team_ids
        self.services = services
        self.services_by_id = {service.id: service for service in services}

    @abstractmethod
    def calculate_scoring_for_tick(
        self,
        current_tick: int,
        checker_results: Mapping[int, Mapping[TeamServicePair, tuple[str, Mapping | None]]],
        last_tick_points: dict[TeamServicePair, TeamPointsLite],
        _prev_attacking: Mapping[tuple[int, int, int], Mapping[int, set[int]]],
        _num_active: Mapping[int, set[int]],
        flags: list[StolenFlag],
    ) -> dict[TeamServicePair, TeamPointsLite]:
        raise NotImplementedError()


class ScoreTickAlgorithmAtklab(
    ScoreTickAlgorithm, ABC
):
    """
    Positive, monotonic ECSC A/D scoring:
    - ATK: valid submitted flags always add positive points.
    - SLA: up services contribute to the service SLA multiplier.
    - DEF: up services add defense points when no valid flag was stolen from them in
      the current tick.
    """

    BASE_ATTACK_POINTS: float = 10.0
    BASE_DEFENSE_POINTS: float = 5.0

    def _service_flag_count(self, service_id: int) -> float:
        return max(float(self.services_by_id[service_id].flags_per_tick), 1.0)

    def _flag_store_count(self, service_id: int) -> int:
        return max(int(self.services_by_id[service_id].flags_per_tick), 1)

    def _service_health(
        self,
        current_tick: int,
        service_id: int,
        status: str,
        getflags: Mapping[str, str] | None,
    ) -> float:
        if status == "SUCCESS":
            return 1.0
        if status != "RECOVERING" or getflags is None:
            return 0.0

        ok_flags = 0
        expected_flags = self.config.flags_rounds_valid * self._flag_store_count(
            service_id
        )
        for related_tick in range(
            current_tick - self.config.flags_rounds_valid + 1, current_tick + 1
        ):
            for flagstore_id in range(self._flag_store_count(service_id)):
                ok_flags += getflags.get(f"{related_tick}_{flagstore_id}") == "OK"
        return ok_flags / max(expected_flags, 1)

    def _attack_points(self, service_id: int) -> float:
        return (
            self.BASE_ATTACK_POINTS
            / self._service_flag_count(service_id)
            * self.config.off_factor
        )

    def _defense_points(self, service_id: int) -> float:
        return (
            self.BASE_DEFENSE_POINTS
            * self._service_flag_count(service_id)
            * self.config.def_factor
        )

    def _is_valid_flag_submission(self, current_tick: int, flag: SubmittedFlag) -> bool:
        if flag.team_id == self.config.nop_team_id:
            return False
        if flag.submitted_by == self.config.nop_team_id:
            return False
        if flag.submitted_by == flag.team_id:
            return False
        if flag.tick_issued <= current_tick - self.config.flags_rounds_valid:
            return False
        return True

    def calculate_scoring_for_tick(
        self,
        current_tick: int,
        checker_results: Mapping[int, Mapping[TeamServicePair, tuple[str, Mapping | None]]],
        last_tick_points: dict[TeamServicePair, TeamPointsLite],
        _prev_attacking: Mapping[tuple[int, int, int], Mapping[int, set[int]]],
        _num_active: Mapping[int, set[int]],
        flags: list[StolenFlag],
    ) -> dict[TeamServicePair, TeamPointsLite]:
        """
        Calculate the results for one tick
        """

        # 1. Spaces for results
        new_tick_points: dict[TeamServicePair, TeamPointsLite] = {}
        for team_id in self.team_ids:
            for service in self.services:
                new_tick_points[(team_id, service.id)] = TeamPointsLite(
                    team_id=team_id, service_id=service.id, tick=current_tick
                )

        # 2. Calculate this tick's service health.
        service_health: dict[TeamServicePair, float] = {}
        for (team_id, service_id), teampoints in new_tick_points.items():
            status, getflags = checker_results[current_tick][(team_id, service_id)]
            health = self._service_health(current_tick, service_id, status, getflags)
            service_health[(team_id, service_id)] = health
            teampoints.sla_delta = health * self.config.sla_factor

        # 3. Distribute positive attack points for all valid flags submitted this tick.
        stolen_flags = FlagSet()
        hacked_services: set[TeamServicePair] = set()
        for flag in flags:
            if not self._is_valid_flag_submission(current_tick, flag.flag):
                continue

            try:
                victim = new_tick_points[(flag.flag.team_id, flag.flag.service_id)]
                hacked_services.add((flag.flag.team_id, flag.flag.service_id))

                attacker = new_tick_points[(flag.flag.submitted_by, flag.flag.service_id)]
                attacker.flag_captured_count += 1
                attacker.off_points += self._attack_points(flag.flag.service_id)

                if stolen_flags.is_new(flag.flag):  # once per flag
                    if flag.num_previous_submissions == 0:
                        victim.flag_stolen_count += 1
            except KeyError:
                print(
                    f"Flag submitted for invalid team/service: "
                    f"flag #{flag.flag.id} ({flag.flag.team_id}, {flag.flag.service_id})"
                )
                log(
                    "scoring",
                    "Flag submitted for invalid team/service",
                    f"flag #{flag.flag.id} ({flag.flag.team_id}, {flag.flag.service_id})",
                    level=LogMessage.WARNING,
                )

        # 4. Award positive defense points for services that stayed up and were not
        # hacked during this tick.
        for (team_id, service_id), teampoints in new_tick_points.items():
            if team_id == self.config.nop_team_id:
                continue
            if (team_id, service_id) in hacked_services:
                continue
            if service_health[(team_id, service_id)] <= 0:
                continue
            teampoints.def_points += self._defense_points(service_id)

        # 5. Add the points from previous tick
        for (team_id, service_id), teampoints in new_tick_points.items():
            lr = last_tick_points[(team_id, service_id)]
            teampoints.off_points += lr.off_points
            teampoints.def_points += lr.def_points
            teampoints.sla_points = (
                (lr.sla_points * (current_tick - 1)) + teampoints.sla_delta
            ) / current_tick
            teampoints.flag_captured_count += lr.flag_captured_count
            teampoints.flag_stolen_count += lr.flag_stolen_count

        return new_tick_points
