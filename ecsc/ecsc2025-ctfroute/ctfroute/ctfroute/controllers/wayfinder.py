import asyncio
from functools import partial
from logging import getLogger
from typing import NamedTuple

from ctfroute.controllers.base import Controller, InternalUpdate
from ctfroute.drivers.base import RouterConnection, RouterConnectivityDriver
from ctfroute.drivers.exceptions import SoftFail
from ctfroute.drivers.hostname.driver import HostnameRouterConnectivityDriver
from ctfroute.drivers.wireguard.driver import WireGuardRouterConnectivityDriver
from ctfroute.state.external import RouterId
from ctfroute.state.internal import Router, Team
from ctfroute.state.utils import AreEqual, are_equal
from ctfroute.utils import EntityType

LOGGER = getLogger(__name__)

DRIVERS: dict[str, type[RouterConnectivityDriver]] = {
    HostnameRouterConnectivityDriver.name: HostnameRouterConnectivityDriver,
    WireGuardRouterConnectivityDriver.name: WireGuardRouterConnectivityDriver,
}


class WayFinder(Controller):
    """WayFinder ensures that traffic finds it's way to the appropriate routers."""

    RECONNECT_RETRY_DELAY = 1

    class KEYS(NamedTuple):
        STATE: str

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._drivers: dict[str, RouterConnectivityDriver] = {}
        self.connections: dict[RouterId, RouterConnection] = {}

    equal_teams: AreEqual[Team] = staticmethod(
        partial(are_equal, fields=("id", "network"))
    )
    equal_routers: AreEqual[Router] = staticmethod(
        partial(are_equal, fields=("id", "host", "teams", "connectivity"))
    )

    def _router_desired(self, router_id: RouterId) -> bool:
        return any(routers.id == router_id for routers in self.state.routers)

    def get_driver(self, router: Router) -> RouterConnectivityDriver:
        driver_name = router.connectivity.driver
        if driver_name not in self._drivers:
            self._drivers[driver_name] = DRIVERS[driver_name](mtu=self.mtu)
        return self._drivers[driver_name]

    async def _retry_connect(self, router):
        loop = asyncio.get_running_loop()
        driver = self.get_driver(router)
        while self._router_desired(router.id):
            try:
                connection = await driver.connect(router)
                for team_id in router.teams:
                    team = self.state.teamsById[team_id]
                    await connection.route(team)

                for net_entity_id in router.net_entities:
                    net_entity = self.state.netEntitiesById[net_entity_id]
                    await connection.route(net_entity)

                self.connections[router.id] = connection
                loop.create_task(self._monitor(connection))
                break
            except SoftFail as e:
                LOGGER.warning(
                    f"Temporary failure when connecting to router '{router.id}': {e.msg}"
                )
                await asyncio.sleep(self.RECONNECT_RETRY_DELAY)

    async def _monitor(self, connection: RouterConnection):
        router_id = connection.router.id
        last_state = None
        async for state in connection.monitor():
            if last_state != state:
                await self.updates.put(
                    InternalUpdate(
                        entity_type=EntityType.Router,
                        entity_id=router_id,
                        update={f"{self.KEYS.STATE}": state},
                    )
                )
            last_state = state
        # Driver monitoring loop exited -> Router was disconnected
        del self.connections[router_id]

        if self._router_desired(router_id):
            asyncio.get_running_loop().create_task(
                self._retry_connect(connection.router)
            )

    async def _configure_local(self):
        # Future drivers might require error-handling for InsufficientState or
        #  SoftFail, As of writing, no such driver exists.
        router = self.local_router
        driver = self.get_driver(self.local_router)
        await driver.configure_local(router)

    async def _setup(self):
        loop = asyncio.get_running_loop()
        await self._configure_local()
        for router in self.other_routers:
            loop.create_task(self._retry_connect(router))

    async def run(self):
        await self._setup()
        return self._yield_all_updates()

    async def router_update(self, router: Router, delete: bool = False):
        if router.id == self.local_router.id:
            self.state.routersById[router.id] = router
            await self._configure_local()

        if router.id in self.state.routersById and not delete:
            current_state = self.state.routersById[router.id]
            if self.equal_routers(current_state, router):
                # All good, no relevant change
                return

        raise NotImplementedError(
            f"{type(self).__name__} does not support external router updates yet."
        )

    async def team_update(self, team: Team, delete: bool = False):
        if team.id in self.state.teamsById and not delete:
            current_state = self.state.teamsById[team.id]
            if self.equal_teams(current_state, team):
                # All good, no relevant change
                return

        raise NotImplementedError(
            f"{type(self).__name__} does not support external team updates yet."
        )
