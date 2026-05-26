import asyncio
from functools import partial
from logging import getLogger
from typing import NamedTuple

from ctfroute.controllers.base import Controller, InternalUpdate
from ctfroute.drivers.base import AnonymizationDriver, AnonymizationHandle
from ctfroute.drivers.exceptions import InsufficientState
from ctfroute.drivers.netfilter.driver import NetfilterAnonymizationDriver
from ctfroute.state.external import TeamId
from ctfroute.state.internal import Router, Team
from ctfroute.state.utils import AreEqual, are_equal
from ctfroute.utils import EntityType

LOGGER = getLogger(__name__)


DRIVERS: dict[str, type[AnonymizationDriver]] = {
    Driver.name: Driver for Driver in [NetfilterAnonymizationDriver]
}


class Cleaner(Controller):
    class KEYS(NamedTuple):
        STATE: str

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.drivers: dict[str, AnonymizationDriver] = {}

        self.handles: dict[TeamId, AnonymizationHandle] = {}
        # Teams for which the driver raised InsufficientState need to be
        #  re-attempted when their state is updated
        self.incomplete_handles: dict[TeamId, Team] = {}

    equal_teams: AreEqual[Team] = staticmethod(
        partial(
            are_equal,
            fields=("id", "network", "gateway"),
            # TODO: Meta-field concierge sets to indicate interface name?
        )
    )

    def get_driver(self, name: str) -> AnonymizationDriver:
        if name not in self.drivers:
            self.drivers[name] = DRIVERS[name](mtu=self.mtu)
        return self.drivers[name]

    async def _try_set_up_team(self, team: Team) -> None:
        if team.id in self.incomplete_handles:
            del self.incomplete_handles[team.id]
        try:
            driver_name = team.anonymization.driver
            anonymize = team.id in self.local_team_ids
            self.handles[team.id] = await self.get_driver(driver_name).set_up(
                team, anonymize
            )
            await self.updates.put(
                InternalUpdate(
                    entity_type=EntityType.Team,
                    entity_id=team.id,
                    update={self.KEYS.STATE: "anonymized"},
                )
            )
        except InsufficientState as e:
            LOGGER.info(
                f"State insufficient for anonymization of team {team.id}: {e.msg}"
            )
            self.incomplete_handles[team.id] = team
        except Exception:
            LOGGER.exception(
                f"Unexpected error while setting up anon for team {team.id}"
            )
            raise

    def _setup(self):
        loop = asyncio.get_running_loop()
        for team in self.state.teams:
            loop.create_task(self._try_set_up_team(team))

    async def run(self):
        self._setup()
        return self._yield_all_updates()

    async def router_update(self, router: Router, delete: bool = False):
        # Cleaner doesn't care about other routers
        if router.id != self.local_router.id:
            return

        if not delete and self.local_router.teams == router.teams:
            return

        # TODO, Needed because the team <-> router mapping may change
        #  This is rather straight forward: Start anonymizing newly added teams and tear
        #  down anonymization for teams that are no longer assigned to this router
        raise NotImplementedError(
            f"{type(self).__name__} does not support external router updates yet."
        )

    async def team_update(self, team: Team, delete: bool = False):
        if team.id in self.state.teamsById and not delete:
            current_state = self.state.teamsById[team.id]
            if self.equal_teams(current_state, team):
                # All good, nothing left to do here
                return
        elif team.id in self.incomplete_handles and not delete:
            self.state.upsert(team)
            await self._try_set_up_team(team)
            return

        # TODO, Needed because a teams network / interface / etc might change
        raise NotImplementedError(
            f"{type(self).__name__} does not support external team updates yet."
        )
