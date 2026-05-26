__all__ = ["WireGuardRouterConnectivityDriver"]

import asyncio
import logging
from ipaddress import IPv4Address, IPv4Network
from typing import AsyncGenerator

from pyroute2 import NDB, WireGuard

from ctfroute.drivers.base import (
    RouterConnection,
    RouterConnectivityDriver,
)
from ctfroute.drivers.exceptions import SoftFail
from ctfroute.drivers.utils import RouterConnectivityDriverStateBase, try_resolve
from ctfroute.drivers.wireguard.state import WireGuardRouterConnectivity
from ctfroute.state.external import NetEntity
from ctfroute.state.internal import Router, Team

LOGGER = logging.getLogger(__name__)

IFNAME = "router_mesh"

State = RouterConnection.State


class DriverState(RouterConnectivityDriverStateBase):
    def __init__(
        self,
        router_ip: IPv4Address,
        public_key: str,
        allowed_ips: set[IPv4Address | IPv4Network],
    ):
        super().__init__(router_ip)
        self.public_key = public_key
        self.allowed_ips = allowed_ips


class WireGuardRouterConnectivityDriver(RouterConnectivityDriver[DriverState]):
    name = "wireguard"
    check_interval_s: float = 5

    def __init__(self, *, mtu: int) -> None:
        super().__init__(mtu=mtu)
        self._ndb = NDB()
        self._wg = WireGuard()
        self._ifname: str | None = None
        self._passive: bool | None = None

    @property
    def oif_index(self):
        return self._ndb.interfaces[self._ifname].get("index")

    def _route_to_mesh(self, ip: IPv4Address | IPv4Network):
        str_target = str(ip)
        if route := self._ndb.routes.get(str_target):
            route.remove()
            route.commit()
        # Add the new one
        route = self._ndb.routes.create(
            dst=str_target,
            oif=self.oif_index,
        )
        route.commit()

    async def configure_local(self, router: Router) -> None:
        settings = router.connectivity
        assert settings.driver == "wireguard"
        assert isinstance(settings, WireGuardRouterConnectivity)

        self._ifname = settings.ifname or IFNAME
        self._passive = settings.passive

        if self._ifname not in self._ndb.interfaces:
            with self._ndb.interfaces.create(
                kind="wireguard", ifname=self._ifname
            ) as link:
                link.set(state="up")
                if settings.address is not None:
                    link.add_ip(str(IPv4Network(settings.address)))

        self._wg.set(
            self._ifname, private_key=settings.private_key, listen_port=settings.port
        )

    async def connect(self, router: Router) -> RouterConnection[DriverState]:
        ip = await try_resolve(router.host)
        if ip is None:
            raise SoftFail(f"Can't resolve '{router.host}'")

        settings = router.connectivity
        assert settings.driver == "wireguard"
        assert isinstance(settings, WireGuardRouterConnectivity)

        allowed_ips: set[IPv4Address | IPv4Network] = set()
        if addr := settings.address:
            as_cidr = IPv4Network(addr)
            allowed_ips.add(as_cidr)
            self._route_to_mesh(as_cidr)

        peer_settings = {
            "public_key": settings.public_key,
            "persistent_keepalive": 1,
            "allowed_ips": [str(a) for a in allowed_ips],
        }
        if not self._passive:
            peer_settings.update(
                {
                    "endpoint_addr": str(ip),
                    "endpoint_port": settings.port,
                }
            )
        self._wg.set(self._ifname, peer=peer_settings)

        return RouterConnection(
            driver=self,
            router=router.model_copy(deep=True),
            state=State.degraded,
            driver_state=DriverState(
                router_ip=ip,
                public_key=settings.public_key,
                allowed_ips=allowed_ips,
            ),
        )

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
                # TODO: This hogs the event loop like crazy if the peer is down!
                pingable = True
                # pingable = await ping(known_ip)
                resolved_ip = await try_resolve(host)

                # TODO: Check peer status!

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

            await asyncio.sleep(self.check_interval_s)

    async def route(
        self, connection: RouterConnection[DriverState], entity: Team | NetEntity
    ) -> None:
        assert connection.driver_state is not None
        driver_state = connection.driver_state

        new_allowed_ips = [str(ip) for ip in driver_state.allowed_ips]

        targets = self.get_addresses(entity)
        for target in targets:
            self._route_to_mesh(target)
            new_allowed_ips.append(str(target))

        self._wg.set(
            self._ifname,
            peer={
                "public_key": driver_state.public_key,
                "allowed_ips": new_allowed_ips,
            },
        )

        driver_state.allowed_ips |= targets
        driver_state.set(entity)

    async def un_route(
        self, connection: RouterConnection[DriverState], entity: Team | NetEntity
    ) -> None:
        assert connection.driver_state is not None
        driver_state = connection.driver_state

        stored_entity = driver_state.get(entity)
        targets = self.get_addresses(stored_entity)

        for target in targets:
            route = self._ndb.routes[str(target)]
            route.remove()
            route.commit()

        new_allowed_ips = driver_state.allowed_ips - targets

        # Set allowed_ips
        self._wg.set(
            self._ifname,
            peer={
                "public_key": driver_state.public_key,
                "allowed_ips": [str(ip) for ip in new_allowed_ips],
            },
        )
        driver_state.delete(stored_entity)
        driver_state.allowed_ips = new_allowed_ips

    async def disconnect(self, connection: RouterConnection[DriverState]):
        connection.state = State.disconnecting

        # Remove routes
        for addr in connection.driver_state.allowed_ips:
            if route := self._ndb.routes.get(str(addr)):
                route.remove()
                route.commit()

        # Remove peer
        self._wg.set(
            self._ifname,
            peer={"public_key": connection.driver_state.public_key, "remove": True},
        )
        connection.state = State.disconnected
