from base64 import b64decode
from functools import wraps
from ipaddress import IPv4Network
from logging import getLogger
from typing import Any, Sequence, TypedDict

from rest_framework.exceptions import ValidationError

from mainpage.network_lib import TEAM_NET_PREFIX_LEN, get_gateway_address

LOGGER = getLogger(__name__)


def key_error_validation_error(on: str):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                func(*args, **kwargs)
            except KeyError as e:
                raise ValidationError({on: f"Expected field {e} on {on}"}) from e

        return wrapper

    return decorator


def try_cidr(cidr_str: str) -> IPv4Network:
    try:
        return IPv4Network(cidr_str, strict=False)
    except ValueError as e:
        raise ValidationError(
            {"interface.peers[*].cidr": f"Invalid CIDR: {cidr_str}"}
        ) from e


def check_overlap(networks: Sequence[IPv4Network]):
    """Raise ValidationError if any of the networks overlap."""
    for i, a in enumerate(networks):
        for b in networks[i + 1 :]:
            if a.overlaps(b):
                raise ValidationError(
                    {"interface.peers[*].cidr": f"{a} overlaps with {b}"}
                )


def check_valid_for_team(team_net: IPv4Network, networks: list[IPv4Network]):
    """Raise ValidationError if any of the networks are not in the team network."""
    gateway = get_gateway_address(team_net)
    for net in networks:
        if not team_net.supernet_of(net):
            message = f"All peers must be in the same /{TEAM_NET_PREFIX_LEN}."
            extra: dict[str, Any] = {"event.name": "security.suspicious"}
            LOGGER.warning(f"Sus: {message}", extra)
            raise ValidationError({"interface.peers[*].cidr": message})
        if gateway in net:
            message = f"{net} overlaps with the gateway address."
            raise ValidationError({"interface.peers[*].cidr": message})


class Peer(TypedDict):
    key_slot: int
    cidr: str
    enabled: bool
    order: int


class Interface(TypedDict):
    peers: list[Peer]
    cidr: str


class KeySlot(TypedDict):
    name: str
    public_key: str | None


class PeersValidator:
    @key_error_validation_error(on="interface")
    def __call__(self, value: Interface):
        peers = value["peers"]
        self.check_peers(peers=peers)

    @key_error_validation_error(on="interface.peers[*]")
    def check_peers(self, peers: list[Peer]):
        """
        Check if the peer config is consistent.

        This is not sufficient overall, because at this stage we don't know the user's
        real team network and managed peers might be omitted from the request payload.
        Doing the validation here gives users faster responses for obvious errors and
        stops bad updates from pressuring the DB.
        """
        if len(peers) == 0:
            raise ValidationError({"interface.peers": "No peers provided"})

        # We guesstimate the team net here and then check if it matches the real one
        # in the update method
        first_cidr = try_cidr(peers[0]["cidr"])
        team_net = IPv4Network(
            (first_cidr.network_address, TEAM_NET_PREFIX_LEN), strict=False
        )

        enabled_peers = sum(peer["enabled"] for peer in peers)
        key_slots_used = set(
            peer["key_slot"] for peer in peers if peer["enabled"] is True
        )
        if enabled_peers != len(key_slots_used):
            raise ValidationError(
                {
                    "interface.peers[*].key_slot": "Key Slots must be unique among"
                    " enabled peers."
                }
            )

        peer_nets: list[IPv4Network] = [try_cidr(peer["cidr"]) for peer in peers]
        check_valid_for_team(team_net, peer_nets)
        check_overlap(peer_nets)


class KeySlotValidator:
    def __call__(self, value: KeySlot) -> None:
        if "public_key" in value and value["public_key"] is not None:
            try:
                b64decode(value["public_key"])
            except ValueError as e:
                raise ValidationError(
                    {"keyslot.public_key": f"No valid public key ({str(e)})"}
                )
