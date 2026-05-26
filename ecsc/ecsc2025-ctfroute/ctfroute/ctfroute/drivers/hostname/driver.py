__all__ = ["HostnameRouterConnectivityDriver"]
import asyncio
from logging import getLogger
from typing import AsyncGenerator

from pyroute2 import NDB

from ctfroute.drivers.base import RouterConnection, RouterConnectivityDriver
from ctfroute.drivers.exceptions import SoftFail
from ctfroute.drivers.utils import RouterConnectivityDriverStateBase, try_resolve
from ctfroute.state.external import NetEntity
from ctfroute.state.internal import Router, Team
from ctfroute.utils import ping

LOGGER = getLogger(__name__)

State = RouterConnection.State


class DriverState(RouterConnectivityDriverStateBase): ...


class HostnameRouterConnectivityDriver(RouterConnectivityDriver[DriverState]):
    name = "hostname"
    ping_interval_s = 1

    def __init__(self, *, mtu: int):
        super().__init__(mtu=mtu)
        self._ndb = NDB()

    async def configure_local(self, router: Router):
        """Noop, this driver only sets routes."""

    async def connect(self, router: Router) -> RouterConnection[DriverState]:
        """
        Set up connectivity to a router.

        Raises:
            SoftFail: If the hostname of the router cannot be resolved.
        """
        ip = await try_resolve(router.host)
        if ip is None:
            raise SoftFail(f"Can't resolve '{router.host}'")

        pingable = await ping(ip)
        if not pingable:
            raise SoftFail(f"Can't ping {ip}")

        LOGGER.info(f"Connected to {router.host} via {ip}")
        connection = RouterConnection(
            driver=self,
            router=router.model_copy(deep=True),
            state=State.connected,
            driver_state=DriverState(
                router_ip=ip,
            ),
        )

        return connection

    async def monitor(
        self, connection: RouterConnection[DriverState]
    ) -> AsyncGenerator[RouterConnection.State, None]:
        assert connection.driver_state is not None
        while True:
            if connection.state == State.disconnecting:
                yield connection.state
            elif connection.state in (State.connected, State.degraded):
                known_ip = connection.driver_state.router_ip
                host = connection.router.host
                pingable = await ping(known_ip)
                resolved_ip = await try_resolve(host)

                if pingable and resolved_ip == known_ip:
                    connection.state = State.connected
                elif (resolved_ip is None) or not pingable:
                    connection.state = State.degraded

                if resolved_ip not in (known_ip, None):
                    LOGGER.warning(f"{host} ip address changed, disconnecting.")
                    await self.disconnect(connection)

                yield connection.state
            elif connection.state == State.disconnected:
                return
            else:
                raise NotImplementedError(
                    f"Unhandled connection state {connection.state}"
                )

            await asyncio.sleep(self.ping_interval_s)

    async def route(
        self, connection: RouterConnection[DriverState], entity: Team | NetEntity
    ) -> None:
        assert connection.driver_state is not None
        driver_state = connection.driver_state

        gateway = str(driver_state.router_ip)
        targets = self.get_addresses(entity)
        for target in targets:
            str_target = str(target)
            # There might be an old route from a previous instance of ctfroute
            if route := self._ndb.routes.get(str_target):
                route.remove()
                route.commit()
            route = self._ndb.routes.create(
                dst=str_target,
                gateway=gateway,
            )
            route.commit()
        driver_state.set(entity)

    async def un_route(
        self, connection: RouterConnection[DriverState], entity: Team | NetEntity
    ) -> None:
        assert connection.driver_state is not None
        driver_state = connection.driver_state

        stored_entity = driver_state.get(entity)
        targets = self.get_addresses(stored_entity)
        for target in targets:
            str_target = str(target)
            if route := self._ndb.routes.get(str_target):
                route.remove()
                route.commit()

        driver_state.delete(stored_entity)

    async def disconnect(self, connection: RouterConnection[DriverState]) -> None:
        assert connection.driver_state is not None
        connection.state = State.disconnecting
        # Remove routes
        #  TODO: Maybe this is something  Wayfinder should do instead of drivers?
        for team in list(connection.driver_state.teams.values()):
            await self.un_route(connection, team)

        connection.state = State.disconnected
