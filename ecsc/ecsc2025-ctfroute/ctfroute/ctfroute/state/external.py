"""
These classes are used to (de)serialize the state from/to external systems.

E.g., Yaml config files, etc.
"""

__all__ = [
    "NET_REF_PATTERN",
    "BaseGate",
    "CtfNetwork",
    "CtfRouteState",
    "Gate",
    "GateId",
    "GateType",
    "GenericCtfRouteState",
    "HTBClass",
    "HTBClassTemplate",
    "NetEntity",
    "NetEntityId",
    "NetRef",
    "NetRefKeyword",
    "NetRefPrefix",
    "Router",
    "RouterId",
    "Team",
    "TeamId",
    "TeamTrafficControl",
    "TrafficControl",
]

from abc import ABC
from enum import StrEnum
from functools import cached_property
from ipaddress import IPv4Address, IPv4Network
from typing import Annotated, Generic, Literal, Optional, Self, TypeVar, assert_never

from pydantic import AwareDatetime, Field, model_validator

from ctfroute.defs import (
    IFNAME_PATTERN,
    NET_ENT_MAX_LEN,
    NET_REF_PATTERN,
    NetRefKeyword,
    NetRefPrefix,
)
from ctfroute.drivers.hostname.state import HostnameRouterConnectivity
from ctfroute.drivers.netfilter.state import NetfilterAnonymization
from ctfroute.drivers.wireguard.state import (
    WireGuardRouterConnectivity,
    WireGuardTeamConnectivity,
)
from ctfroute.state.base import CtfRouteBaseModel
from ctfroute.state.utils import FilterView

# Entity ids are treated as strings internally to discourage writing code that relies on
# numeric properties of ids. However, we don't want to be petty when reading desired
# state from external sources, e.g. requiring quotes on numeric ids in yaml, so we
# coerce numbers to strings.
TeamId = Annotated[
    str,
    Field(
        coerce_numbers_to_str=True,
        max_length=NET_ENT_MAX_LEN,
        # Team ids are used in interface names...
        pattern=IFNAME_PATTERN,
    ),
]
RouterId = Annotated[str, Field(coerce_numbers_to_str=True)]
GateId = Annotated[str, Field(coerce_numbers_to_str=True)]
NetEntityId = Annotated[
    str,
    Field(
        coerce_numbers_to_str=True,
        max_length=NET_ENT_MAX_LEN,
        # As of writing NetEntity IDs aren't used in interface names, but it might
        # become a thing. It's easier to just be consistent with team ids
        pattern=IFNAME_PATTERN,
    ),
]


# Additional network entities that can be configured for your game
class NetEntity(CtfRouteBaseModel):
    id: NetEntityId
    # Optional so you can define gates / rules with them before actually
    # populating their ip addresses
    addresses: Optional[set[IPv4Network]] = Field(default_factory=set)
    # Interface over which this entity will be reached
    # Necessary if you wish to shape the traffic to / from this entity
    interface: Optional[str] = None


class HTBClassTemplate(CtfRouteBaseModel):
    original: Optional[str] = None
    reply: Optional[str] = None
    params: Optional[str] = None
    qdisc: Optional[str] = None

    @model_validator(mode="after")
    def check_params(self) -> Self:
        params_set = self.params is not None
        dir_params_set = self.original is not None and self.reply is not None

        if not params_set ^ dir_params_set:
            raise ValueError(
                "Either params or original and reply need to be set on a"
                " HTBClass(Template)"
            )

        return self


class HTBClass(HTBClassTemplate):
    # Addresses
    addresses: Optional[set[IPv4Network]] = None
    # Nft expressions
    match: Optional[set[str]] = None


class TrafficControl(CtfRouteBaseModel):
    default: HTBClassTemplate
    classes: Optional[list[HTBClass]] = None


class TeamTrafficControl(TrafficControl):
    team: HTBClassTemplate
    internal: Optional[HTBClassTemplate] = None
    net_entities: Optional[dict[NetEntityId, HTBClassTemplate | None]] = None


# Settings for the overall ctf network
class CtfNetwork(CtfRouteBaseModel):
    mtu: Optional[int] = None
    entities: Optional[list[NetEntity]] = Field(default_factory=list)
    nft: Optional[str] = None  # additional nft rules
    team_traffic_control: Optional[TeamTrafficControl] = None
    # Maps interface name to TC config
    traffic_control: Optional[dict[str, TrafficControl]] = None


NetRef = Annotated[str, Field(coerce_numbers_to_str=True, pattern=NET_REF_PATTERN)]


class Period(CtfRouteBaseModel):
    # See https://docs.pydantic.dev/2.1/usage/types/datetime/
    from_time: Optional[AwareDatetime] = None
    to_time: Optional[AwareDatetime] = None


class GateType(StrEnum):
    connection = "connection"
    raw = "raw"


class BaseGate(CtfRouteBaseModel, ABC):
    id: GateId
    type: GateType
    period: Optional[Period] = None


class ConnGate(BaseGate):
    type: Literal[GateType.connection] = GateType.connection
    conn_src: NetRef | None = None
    conn_dst: NetRef | None = None
    # Here you can add an nft expression to limit the scope of your gate, e.g.:
    # tcp dport 2000
    expression: Optional[str] = None


class RawGate(BaseGate):
    type: Literal[GateType.raw] = GateType.raw
    rule: str


Gate = ConnGate | RawGate


class Team(CtfRouteBaseModel):
    id: TeamId
    network: IPv4Network
    gateway: IPv4Address | None = None
    vulnbox: IPv4Address | None = None
    meta: dict[str, str] = Field(default_factory=dict)
    connectivity: WireGuardTeamConnectivity = Field(discriminator="driver")
    # Optional because a default may be specified in the config file
    anonymization: Optional[NetfilterAnonymization] = Field(
        discriminator="driver", default=None
    )


class Router(CtfRouteBaseModel):
    id: RouterId
    host: str
    teams: Optional[set[TeamId]] = Field(default_factory=set)
    net_entities: Optional[set[NetEntityId]] = Field(default_factory=set)

    # Optional because a default may be specified in the config file
    connectivity: Optional[HostnameRouterConnectivity | WireGuardRouterConnectivity] = (
        Field(discriminator="driver", default=None)
    )


TeamT = TypeVar("TeamT", bound=Team)
RouterT = TypeVar("RouterT", bound=Router)
GateT = TypeVar("GateT", bound=Gate)


class GenericCtfRouteState(CtfRouteBaseModel, Generic[TeamT, RouterT, GateT]):
    network: Optional[CtfNetwork] = Field(default_factory=CtfNetwork)
    teams: list[TeamT] = Field(default_factory=list)
    routers: list[RouterT] = Field(default_factory=list)
    gates: list[Annotated[GateT, Field(discriminator="type")]] = Field(
        default_factory=list
    )

    @cached_property
    def teamsById(self) -> FilterView[TeamT, TeamId]:
        return FilterView(self, "teams", "id")

    @cached_property
    def netEntitiesById(self) -> FilterView[NetEntity, NetEntityId]:
        return FilterView(self, "network.entities", "id")

    @cached_property
    def routersById(self) -> FilterView[RouterT, RouterId]:
        return FilterView(self, "routers", "id")

    @cached_property
    def gatesById(self) -> FilterView[GateT, GateId]:
        return FilterView(self, "gates", "id")

    def delete(self, entity: TeamT | RouterT | GateT, raise_if_absent: bool = False):
        if isinstance(entity, Team):
            if raise_if_absent or entity.id in self.teamsById:
                del self.teamsById[entity.id]
        elif isinstance(entity, Router):
            if raise_if_absent or entity.id in self.routersById:
                del self.routersById[entity.id]
        elif isinstance(entity, RawGate) or isinstance(entity, ConnGate):
            if raise_if_absent or entity.id in self.gatesById:
                del self.gatesById[entity.id]
        else:
            assert_never(entity)

    def upsert(self, entity: TeamT | RouterT | GateT):
        if isinstance(entity, Team):
            self.teamsById[entity.id] = entity
        elif isinstance(entity, Router):
            self.routersById[entity.id] = entity
        elif isinstance(entity, RawGate) or isinstance(entity, ConnGate):
            self.gatesById[entity.id] = entity
        else:
            assert_never(entity)


class CtfRouteState(GenericCtfRouteState[Team, Router, GateT]): ...


AnyExternalEntity = Router | Team | Gate
