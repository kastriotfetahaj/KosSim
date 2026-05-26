"""
Base classes for drivers.

These classes define the interfaces that drives must implement. You should be using
these base classes over concrete driver implementations in code of controllers.

Drivers are the layer between controllers and the linux network stack. The classes here
define the actions controllers can take to achieve the desired state. Controllers decide
when to do what, drivers implement the "how".

Example:
When setting up a router, Wayfinder will determine that a teams network needs to be
routed to a specific other router. So it will create a RouterConnection and invoke
connection.route(team).

The HostnameRouterConnectivityDriver "connects" to another router by merely verifying
it is reachable via ICMP ping and route the team by setting a route for the teams
network to that router. In contrast, a wireguard equivalent would have to connect by
setting up an appropriate wg-interface and peer. Routing the team would involve setting
allowedIPs on the wg peer in addition to the appropriate device-route.
"""

__all__ = [
    "AnonymizationDriver",
    "AnonymizationHandle",
    "RouterConnection",
    "RouterConnectivityDriver",
    "TeamConnectivityDriver",
]
from abc import ABC, abstractmethod
from enum import StrEnum
from ipaddress import IPv4Address, IPv4Network
from typing import AsyncGenerator, Generic, TypeVar, assert_never

from ctfroute.drivers.exceptions import InsufficientState
from ctfroute.state.external import NetEntity
from ctfroute.state.internal import Router, Team

# Driver implementations may choose to attach some driver-specific state to the handles
# created by them, e.g.: RouterConnection and AnonymizationHandle
DriverStateT = TypeVar("DriverStateT")


# TODO: This likely needs a refactor including creating a Handle-class and everything
class TeamConnectivityDriver(ABC):
    """Base class for team connectivity drivers."""

    name: str

    def __init__(self, *, mtu: int) -> None:
        self.mtu = mtu

    @abstractmethod
    async def sync(self, team: Team) -> str:
        """
        Bring a team's connectivity into the desired state.

        Usually a vpn interface of sorts.
        """

    @abstractmethod
    async def teardown(self, team: Team) -> None:
        """
        Tear down a team's connectivity.

        Usually a vpn interface of sorts.
        """


class RouterConnection(Generic[DriverStateT]):
    """
    Encapsulates the state for connectivity between this and another router.

    This class provides a handle for a router-router connection that is shared
    between Wayfinder and driver implementations. The data contained in it may only be
    manipulated by the driver or the class itself, not by Wayfinder. It is WayFinder's
    responsibility to store connections until they are disconnected.
    """

    class AlreadyMonitoring(Exception):
        """Raised when monitor() is called more than once on a given connection."""

    class State(StrEnum):
        connected = "connected"  # works
        # Configured, but health-checks in monitoring loop aren't happy
        degraded = "degraded"
        disconnecting = "disconnecting"  # Disconnect was initiated
        disconnected = "disconnected"  # Connection is now worthless

    def __init__(
        self,
        router: Router,
        driver: "RouterConnectivityDriver",
        state: State,
        driver_state: DriverStateT,
    ):
        self.driver = driver
        self.router = router
        self.state = state
        self._monitoring: bool = False
        self.driver_state: DriverStateT = driver_state

    # For more exhaustive documentation check the driver base class!

    def monitor(self) -> AsyncGenerator[State, None]:
        """Monitor the connection, yielding state updates."""
        if self._monitoring:
            # One connection shouldn't have multiple monitoring loops running. Since
            # the driver shouldn't be bothered with such state, we implement this
            # mechanism here.
            raise self.AlreadyMonitoring()
        self._monitoring = True
        return self.driver.monitor(self)

    async def route(self, entity: Team | NetEntity):
        """Ensure the traffic for a team is routed over this connection."""
        await self.driver.route(self, entity)

    async def un_route(self, entity: Team | NetEntity):
        """Ensure the traffic for a team is no longer routed over this connection."""
        await self.driver.un_route(self, entity)

    async def disconnect(self) -> None:
        """Disconnect the router."""
        await self.driver.disconnect(self)


class RouterConnectivityDriver(Generic[DriverStateT]):
    """
    Connect routers and route team traffic.

    To minimize disruption in case the team <-> router mapping changes, the driver
    needs to support setting up and removing routes for specific teams.
    """

    name: str

    def __init__(self, *, mtu: int):
        self.mtu = mtu

    @abstractmethod
    async def configure_local(self, router: Router):
        """
        Set up the local networking.

        Controller should pass the "local" router. Might raise InsufficientState
        """

    @abstractmethod
    async def connect(self, router: Router) -> RouterConnection[DriverStateT]:
        """Connect to router and return a connection handle for it."""

    @abstractmethod
    def monitor(
        self, connection: RouterConnection[DriverStateT]
    ) -> AsyncGenerator[RouterConnection.State, None]:
        """Monitor the passed connection, yielding state updates."""

    @staticmethod
    def get_addresses(entity: NetEntity | Team) -> set[IPv4Network | IPv4Address]:
        targets: set[IPv4Network | IPv4Address] = set()
        if isinstance(entity, NetEntity):
            if entity.addresses:
                for address in entity.addresses:
                    targets.add(address)
        elif isinstance(entity, Team):
            if not entity.network:
                raise InsufficientState("Can't route team without network.")
            else:
                targets.add(entity.network)
        else:
            assert_never(entity)
        return targets

    @abstractmethod
    async def route(
        self, connection: RouterConnection[DriverStateT], enitity: Team | NetEntity
    ) -> None:
        """Ensure the traffic for a team is routed to this node."""

    @abstractmethod
    async def un_route(
        self, connection: RouterConnection[DriverStateT], entity: Team | NetEntity
    ) -> None:
        """Ensure traffic for a team is no longer routed to this node."""

    @abstractmethod
    async def disconnect(self, connection: RouterConnection[DriverStateT]):
        """
        Terminate the connection.

        This should cause the generators returned by connection.monitor to
        eventually close.
        """


class AnonymizationHandle(Generic[DriverStateT]):
    """
    Encapsulates the state of anonymization for a team.

    This class provides a place for anonymization drivers to store information that
    might need to be recalled during teardown. The data contained in it may only be
    manipulated by the driver or the class itself, not by Cleaner. It is Cleaner's
    responsibility to store these handles until they are torn down.
    """

    def __init__(
        self,
        team: Team,
        anonymized: bool,
        driver: "AnonymizationDriver",
        driver_state: DriverStateT,
    ):
        self.team = team
        self.anonymized = anonymized
        self.driver_state = driver_state
        self.driver = driver

    # For more exhaustive documentation check the driver base class!

    async def tear_down(self) -> None:
        """Tear down the anonymization setup."""
        await self.driver.tear_down(self)


class AnonymizationDriver(Generic[DriverStateT]):
    """
    Set up anonymization.

    Anonymization is always performed on the router that hosts a teams
    connectivity-endpoint, so we anonymize "local" teams. However, all known teams need
    to be passed to the driver in order to guarantee correct functionality. Whether
    the traffic should be anonymized or not needs to be indicated when calling set_up.

    The result of invoking driver.set_up(team) should be that the passed team can no
    longer distinguish inbound connections with respect to whether they are coming from
    checkers vs. other teams (or what specific other team).

    We currently make no effort for drivers to support "updating" an existing
    anonymization-setup. The controller needs to tear down the existing one and create
    a new one.
    """

    name: str

    def __init__(self, *, mtu: int):
        self.mtu = mtu

    @abstractmethod
    async def set_up(
        self, team: Team, anonymize: bool
    ) -> AnonymizationHandle[DriverStateT]:
        """
        Set up traffic anonymization for a local team.

        InsufficientState may be raised to indicate missing state - including missing
        meta - in that case Cleaner shall reattempt setup once any update to state was
        made.
        """

    @abstractmethod
    async def tear_down(self, handle: AnonymizationHandle[DriverStateT]) -> None:
        """
        Tear down anonymization for team in a fire-and-forget fashion.

        Tear down anything that relates to the anonymization for the passed team.
        No errors are raised if the anonymization setup for this team is currently
        incorrect, incomplete or absent. Only errors in the teardown procedure
        itself will be raised.
        """
