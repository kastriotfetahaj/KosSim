"""
Dataclasses to represent state internally.

These classes are used to handle state inside a ctfroute instance. The primary
difference extending all entities with the "internal_state" field, for inter-controller
communication.
"""

__all__ = [
    "AnyInternalEntity",
    "ConnGate",
    "CtfRouteState",
    "Gate",
    "RawGate",
    "Router",
    "Team",
    "to_external",
    "to_internal",
]

from typing import assert_never, overload

from ctfroute.drivers.hostname.state import HostnameRouterConnectivity
from ctfroute.drivers.netfilter.state import NetfilterAnonymization
from ctfroute.drivers.wireguard.state import WireGuardRouterConnectivity
from ctfroute.state import external
from ctfroute.state.utils import InternalMixin


class ConnGate(external.ConnGate, InternalMixin): ...


class RawGate(external.RawGate, InternalMixin): ...


Gate = ConnGate | RawGate


class Team(external.Team, InternalMixin):
    # On internal structures, this is no longer optional
    anonymization: NetfilterAnonymization


class Router(external.Router, InternalMixin):
    # On internal structures, this is no longer optional
    connectivity: HostnameRouterConnectivity | WireGuardRouterConnectivity


AnyInternalEntity = Router | Team | Gate


@overload
def to_internal(entity: external.Team) -> Team: ...


@overload
def to_internal(entity: external.Router) -> Router: ...


@overload
def to_internal(entity: external.Gate) -> Gate: ...


def to_internal(entity: external.AnyExternalEntity) -> AnyInternalEntity:
    if isinstance(entity, external.Router):
        return Router(**entity.model_dump())
    if isinstance(entity, external.Team):
        return Team(**entity.model_dump())

    if isinstance(entity, external.RawGate):
        return RawGate(**entity.model_dump())
    if isinstance(entity, external.ConnGate):
        return ConnGate(**entity.model_dump())

    assert_never(entity)


@overload
def to_external(entity: Team) -> external.Team: ...


@overload
def to_external(entity: Router) -> external.Router: ...


@overload
def to_external(entity: Gate) -> external.Gate: ...


def to_external(entity: AnyInternalEntity) -> external.AnyExternalEntity:
    model_dumped = entity.model_dump()
    del model_dumped["internal_state"]

    if isinstance(entity, Router):
        return external.Router(**model_dumped)
    if isinstance(entity, Team):
        return external.Team(**model_dumped)

    if isinstance(entity, RawGate):
        return external.RawGate(**model_dumped)
    if isinstance(entity, ConnGate):
        return external.ConnGate(**model_dumped)

    assert_never(entity)


class CtfRouteState(external.GenericCtfRouteState[Team, Router, Gate]):
    @classmethod
    def from_initial(cls, initial: external.CtfRouteState) -> "CtfRouteState":
        return cls(
            teams=[to_internal(team) for team in initial.teams],
            routers=[to_internal(router) for router in initial.routers],
            gates=[to_internal(gate) for gate in initial.gates],
            network=initial.network.model_copy(deep=True) if initial.network else None,
        )
