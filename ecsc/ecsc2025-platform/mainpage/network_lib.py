from functools import cache
from ipaddress import IPv4Address, IPv4Network
from typing import cast

from constance import config
from django.db import transaction
from django.template import Context, Template
from django.utils import timezone

from mainpage.models import Interface, KeySlot, Peer, Player, TeamProfile
from mainpage.utils import gen_wg_keypair

GATEWAY_LAST_OCTET = 254
TEAM_NET_PREFIX_LEN = 24


def get_team_vpn_port(team_id: int) -> int:
    return config.VPN_BASE_PORT + team_id


def get_team_ip(team_id: int, suffix: str | int = "0") -> str:
    if team_id is None:
        return None  # type: ignore
    network_index = config.CTF_META["network_index"]
    return f"10.{network_index}.{team_id}.{suffix}"


def get_vulnbox_cidr(team_id: int) -> str:
    return get_team_ip(team_id, "2/32")


def cidr_intersect(cidr1: str, cidr2: str) -> bool:
    net1 = IPv4Network(cidr1, strict=False)
    net2 = IPv4Network(cidr2, strict=False)
    return net1.overlaps(net2)


@cache
def get_gateway_address(team_network: IPv4Network) -> IPv4Address:
    return get_specific_address(team_network, GATEWAY_LAST_OCTET)


def get_specific_address(network: IPv4Network, last_octet: int) -> IPv4Address:
    # I don't like it but the ipaddress classes don't have a nice way of deriving
    # addresses from one another :/
    prefix, _ = str(network.network_address).rsplit(".", maxsplit=1)
    return IPv4Address(f"{prefix}.{last_octet}")


def prepare_team_network(team: TeamProfile) -> None:
    if team.team_id is None:
        raise ValueError("Team has no team_id")

    interface = Interface(
        team=team,
        cidr=get_team_ip(team.team_id, f"{GATEWAY_LAST_OCTET}/24"),
        managed=config.VPN_DEFAULT_MANAGED,
    )
    interface.save()

    captain = Player.objects.get(team=team, role=Player.RoleChoices.CAPTAIN)

    if not config.VPN_DEFAULT_MANAGED:
        privkey, pubkey = gen_wg_keypair()
        vulnbox_keyslot = KeySlot(
            name=f"{team.name}'s cloud-hosted vulnbox",
            owner=captain,
            managed=True,
            public_key=pubkey,
            private_key=privkey,
        )
        vulnbox_keyslot.save()
        Peer(
            interface=interface,
            key_slot=vulnbox_keyslot,
            cidr=get_vulnbox_cidr(team.team_id),
            comment="Peer for the cloud-hosted vulnbox (enable by selecting cloud hosting)",
            type=Peer.TypeChoices.VULNBOX,
            managed=True,
            enabled=team.use_cloudhosting,
            order=0,
        ).save()

        captain_keyslot = KeySlot.objects.filter(owner=captain, managed=False).first()
        # captain likely has a keyslot already (from the player's post-save receiver)
        if captain_keyslot is None:
            # if not, create one
            captain_keyslot = KeySlot(
                name=f"{captain.username}'s personal key",
                owner=captain,
                managed=False,
            )
            captain_keyslot.save()
        Peer(
            interface=interface,
            key_slot=captain_keyslot,
            cidr=get_team_ip(team.team_id, "16/32"),
            order=1,
            managed=False,
        ).save()


def get_conflicting_peers(interface: Interface, cidr: str) -> list[Peer]:
    conflicting = [
        peer
        for peer in interface.peers.filter(enabled=True)
        if peer.cidr
        and IPv4Network(peer.cidr, strict=False).overlaps(
            IPv4Network(cidr, strict=False)
        )
    ]
    return conflicting


@transaction.atomic
def set_team_testing_status(team: TeamProfile, testing_status: bool):
    if team.team_id is None:
        return
    interface = (
        Interface.objects.select_for_update().prefetch_related("peers").get(team=team)
    )
    peer = Peer.objects.filter(
        interface=interface, type=Peer.TypeChoices.TESTING
    ).first()
    if testing_status:
        cidr = get_vulnbox_cidr(team.team_id)
        if not peer:
            priv, pub = gen_wg_keypair()
            key_slot = KeySlot(
                owner=team.captain,
                managed=True,
                name="Keypair for infra test client",
                private_key=priv,
                public_key=pub,
            )
            key_slot.save()
            peer = Peer(
                managed=True,
                comment="Peer for infra test client",
                type=Peer.TypeChoices.TESTING,
                interface=interface,
                key_slot=key_slot,
                cidr=cidr,
            )

        for conflicting in get_conflicting_peers(interface, cidr):
            conflicting.enabled = False
            conflicting.save()
        peer.enabled = True
        peer.save()
    else:
        if peer:
            peer.key_slot.delete()
            peer.delete()

    interface.last_modified = timezone.now()
    interface.save()


def set_team_cloudhosting_status(
    team: TeamProfile, use_cloudhosting: bool
) -> list[str]:
    """
    Set the cloudhosting status of a team.

    (!) Make sure to only run this inside a transaction.atomic statement (!)

    Returns list of messages that might be interesting to the user (disabled peers etc).
    """
    msgs: list[str] = []

    team_interface = (
        Interface.objects.select_for_update().prefetch_related("peers").get(team=team)
    )
    if not config.VPN_DEFAULT_MANAGED:
        vulnbox_peer = team_interface.peers.get(
            type=Peer.TypeChoices.VULNBOX,
            managed=True,
        )
    # enable cloudhosting
    if use_cloudhosting and not team.use_cloudhosting:
        if not config.VPN_DEFAULT_MANAGED:
            for peer in get_conflicting_peers(team_interface, vulnbox_peer.cidr):
                peer.enabled = False
                peer.save()
                msgs.append(
                    f"Disabled peer {peer} because it conflicted with the cloud vulnbox"
                )
        msgs = ["Enabled cloud-hosting for your team"] + msgs
    elif not use_cloudhosting and team.use_cloudhosting:
        msgs += [
            "Disabled cloud-hosting for your team.",
            "You might have to adjust your network configuration for your selfhosted box.",
        ]
    if not config.VPN_DEFAULT_MANAGED:
        vulnbox_peer.enabled = use_cloudhosting
        vulnbox_peer.save()
    team.use_cloudhosting = use_cloudhosting
    team.save()
    team_interface.last_modified = timezone.now()
    team_interface.save()
    return msgs


def get_next_free_ip(team_id: int, interface: Interface) -> str | None:
    # we start assigning IPs from .128 upwards (so that teams can still grab their /25).
    # if that's full, we'll go down to .10.
    enabled_peers = Peer.objects.filter(interface=interface).all()
    cidrs = [IPv4Network(peer.cidr, strict=False) for peer in enabled_peers]
    for last_octet in list(range(128, 254)) + list(range(127, 9, -1)):
        ip = get_team_ip(team_id, last_octet)
        address = IPv4Address(ip)
        if all(address not in cidr for cidr in cidrs):
            return ip
    return None


def assign_next_free_ip_address(
    team: TeamProfile, interface: Interface, keyslot: KeySlot
) -> bool:
    """Try to assign an ip, return whether the interface needs syncing now."""
    needs_sync = False
    team_id = cast(int, team.team_id)
    # TODO: Is this .first() sane?
    peer = Peer.objects.filter(key_slot=keyslot).first()
    if peer is None:
        next_free_ip = get_next_free_ip(team_id, interface)
        if next_free_ip is not None:
            peer = Peer(
                interface=interface,
                key_slot=keyslot,
                comment="auto-assigned IP",
                enabled=True,
                cidr=next_free_ip + "/32",
                managed=False,
            )
            peer.save()
            needs_sync = True
    else:
        # there's already a peer for this key - enable it if there are no collisions
        if peer.enabled or peer.managed:
            return False
        enabled_peers = Peer.objects.filter(interface=interface).all()
        # Fixme: Use more efficient mainpage.views.api.validators.check_overlap
        has_collision = any(
            cidr_intersect(peer.cidr, other_peer.cidr) for other_peer in enabled_peers
        )
        if not has_collision:
            peer.enabled = True
            peer.save()
            needs_sync = True

    return needs_sync


WIREGUARD_TEMPLATE = Template(
    """
{% if Comment %}
# { Comment }
{% endif %}
[Interface]
Address = {{ Address }}
{% if PrivateKey %}
PrivateKey={{ PrivateKey }}
{% else %}
# TODO place your private key here:
PrivateKey=...
{% endif %}
MTU={{ MTU }}

[Peer]
Endpoint={{ Endpoint }}
AllowedIPs={{ AllowedIPs }}  
PublicKey={{ PublicKey }}
PersistentKeepAlive = {{ PersistentKeepAlive }}
""".strip()
)

DEFAULT_MTU = 1420


def get_wireguard_config(peer: Peer) -> str:
    context = Context(
        dict(
            Comment=peer.comment,
            Address=peer.cidr,
            MTU=DEFAULT_MTU,
            PublicKey=peer.interface.public_key,
            PrivateKey=peer.key_slot.private_key,
            Endpoint=f"{peer.effective_vpn_host}:{peer.effective_vpn_port}",
            AllowedIPs=config.VPN_GAME_NET,
            PersistentKeepAlive=20,
        )
    )
    if peer.overrides:
        context.update(peer.overrides)

    # Ensure comment doesn't create a broken config
    if context["Comment"] is not None:
        context["Comment"] = context["Comment"].replace("\n", " ")

    return WIREGUARD_TEMPLATE.render(context)
