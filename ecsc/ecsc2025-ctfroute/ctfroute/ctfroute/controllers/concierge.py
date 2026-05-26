from logging import getLogger
from typing import AsyncGenerator, NamedTuple

from pyroute2 import NetlinkError

from ctfroute.controllers.base import Controller, InternalUpdate
from ctfroute.drivers.exceptions import BadState, InsufficientState
from ctfroute.drivers.wireguard.driver import WireguardTeamConnectivityDriver
from ctfroute.drivers.wireguard.state import (
    WireGuardTeamConnectivity,
)
from ctfroute.state.internal import Router, Team
from ctfroute.utils import EntityType

LOGGER = getLogger(__name__)


class Concierge(Controller):
    """The concierge ensures teams can connect to the infrastructure."""

    class KEYS(NamedTuple):
        IFNAME: str

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.wg_driver = WireguardTeamConnectivityDriver(mtu=self.mtu)

    async def _setup_team_interfaces(
        self, teams: list[Team]
    ) -> AsyncGenerator[tuple[str, str], None]:
        """
        Perform initial setup of team endpoints.

        Args:
            teams: List of teams connected via this node

        Yields:
            Tuple of team id and the interface name

        Raises:
            NetlinkError: If the WireGuard interface could not be created
        """
        for team in teams:
            if isinstance(team.connectivity, WireGuardTeamConnectivity):
                LOGGER.info(f"Ensuring WireGuard for team {team.id}")
                driver = self.wg_driver
            else:
                raise NotImplementedError(f"Unknown driver: {team.connectivity.driver}")

            try:
                team_ifname = await driver.sync(team)
                yield team.id, team_ifname
            except InsufficientState:
                LOGGER.warning(
                    f"Team {team.id} has insufficient information to configure "
                    "connectivity",
                    extra=dict(team_id=team.id),
                    exc_info=True,
                )
            except NetlinkError as e:
                LOGGER.exception(
                    f"Failed to sync WireGuard interface for team {team.id}",
                    extra=dict(team_id=team.id),
                )
                raise e

    async def run(self) -> AsyncGenerator[InternalUpdate]:
        async for team_id, team_ifname in self._setup_team_interfaces(self.local_teams):
            await self.updates.put(
                InternalUpdate(
                    entity_type=EntityType.Team,
                    entity_id=team_id,
                    update={self.KEYS.IFNAME: team_ifname},
                )
            )

        return self._yield_all_updates()

    async def team_update(self, team: Team, delete: bool = False):
        ...
        # raise NotImplementedError

    async def router_update(self, router: Router, delete: bool = False):
        local_router = self.local_router

        # Concierge doesn't care about routers, except the teams assigned to the
        # local router.
        if router.id != local_router.id:
            return

        new_router = router

        if local_router.host != new_router.host:
            raise BadState("Netloc of local router changed!")

        if local_router.teams != new_router.teams:
            # TODO
            raise NotImplementedError("Changing Team->Router mapping not implemented.")
