from ipaddress import IPv4Address, IPv4Network
from typing import Annotated, Literal, Optional

from pydantic import Field

from ctfroute.defs import IFNAME_MAX_LEN, IFNAME_PATTERN
from ctfroute.state.base import CtfRouteBaseModel, RouterConnectivity, TeamConnectivity


class WireGuardPeer(CtfRouteBaseModel):
    allowed_ips: IPv4Network
    public_key: str
    private_key: Optional[str] = None


class WireGuardTeamConnectivity(TeamConnectivity):
    driver: Literal["wireguard"] = "wireguard"
    public_key: str
    private_key: str
    port: int
    peers: list[WireGuardPeer] = Field(default_factory=list)


Ifname = Annotated[
    str,
    Field(
        max_length=IFNAME_MAX_LEN,
        pattern=IFNAME_PATTERN,
    ),
]


class WireGuardRouterConnectivity(RouterConnectivity):
    driver: Literal["wireguard"] = "wireguard"
    public_key: str
    private_key: str
    port: int
    # Optional additional address for the router itself, this allows
    # directly addressing the routers for i.e. monitoring or infra-routers
    # performing NAT for e.g. kubernetes or docker directly running on them
    address: Optional[IPv4Address] = None
    # Override the name of the interface, this is usefull if there are infra-hosts
    # connected to multiple CTFs
    ifname: Optional[Ifname] = None
    # Do not set endpoints of other routers, let them connect to you
    passive: Optional[bool] = False
