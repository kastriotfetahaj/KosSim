from ipaddress import IPv4Network
from typing import List, cast

from constance import config
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.fields import SerializerMethodField
from rest_framework.relations import StringRelatedField
from rest_framework.serializers import ModelSerializer

from mainpage.models import Interface, KeySlot, Peer, Player
from mainpage.network_lib import get_team_vpn_port
from mainpage.utils import get_player_from_request
from mainpage.views.api.validators import (
    KeySlotValidator,
    PeersValidator,
    check_overlap,
    check_valid_for_team,
)
from mainpage.views.api.validators import (
    Peer as PeerDict,
)
from mainpage.views.team import vpn_config_download


class PeerSerializer(ModelSerializer):
    class Meta:
        model = Peer
        read_only_fields = ("managed", "comment", "vpn_host", "vpn_port")
        fields = read_only_fields + ("key_slot", "cidr", "enabled", "order")


class InterfaceSerializer(ModelSerializer):
    peers = SerializerMethodField("get_peers")
    vpn_host = SerializerMethodField("get_vpn_host")
    vpn_port = SerializerMethodField("get_vpn_port")
    id = SerializerMethodField("get_id")

    class Meta:
        model = Interface
        read_only_fields = (
            "id",
            "public_key",
            "cidr",
            "vpn_host",
            "vpn_port",
            "last_modified",
            "last_synced",
            "managed",
        )
        fields = read_only_fields + ("peers", "auto_ip_assignment")
        validators = (PeersValidator(),)

    def get_id(self, interface: Interface):
        return interface.team.team_id

    def get_vpn_host(self, interface: Interface) -> str:
        if interface.vpn_host is not None:
            return interface.vpn_host
        return config.VPN_HOST

    def get_vpn_port(self, interface: Interface) -> int:
        if interface.vpn_port is not None:
            return interface.vpn_port
        team_id = cast(int, interface.team.team_id)
        return get_team_vpn_port(team_id)

    def get_peers(self, interface: Interface) -> List[Peer]:
        peers = list(interface.peers.filter(~Q(type=Peer.TypeChoices.PREPARED_POOL)))
        return PeerSerializer(peers, many=True).data

    def update(self, instance: Interface, validated_data):
        # At this point we can assert that all CIDRs will parse successfully
        new_peers: List[PeerDict] = validated_data.pop("peers")
        # Get network from router ip
        team_net = IPv4Network(instance.cidr, strict=False)

        new_cidrs = [IPv4Network(peer["cidr"], strict=False) for peer in new_peers]
        check_valid_for_team(team_net, new_cidrs)

        with transaction.atomic():
            # Lock interface before fetching managed peers
            locked_interface = Interface.objects.select_for_update().get(id=instance.id)
            enabled_peers = 0
            used_keyslots = set()
            enabled_cidrs = []

            for peer in locked_interface.peers.select_related("key_slot").all():
                if peer.managed:
                    if peer.enabled:
                        enabled_cidrs.append(IPv4Network(peer.cidr, strict=False))
                        enabled_peers += 1
                        used_keyslots.add(peer.key_slot.id)
                else:
                    peer.delete()

            for peer_data in new_peers:
                cidr = IPv4Network(peer_data["cidr"], strict=False)
                enabled_cidrs.append(cidr)
                key_slot = peer_data["key_slot"]
                enabled = peer_data["enabled"]
                if enabled:
                    enabled_peers += 1
                    used_keyslots.add(key_slot)
                Peer(
                    interface=instance,
                    key_slot=key_slot,  # type: ignore
                    cidr=str(cidr),
                    enabled=enabled,
                    order=peer_data["order"],
                ).save()
            if len(used_keyslots) != enabled_peers:
                raise ValidationError(
                    {
                        "interface.peers.[*].key_slot": "Key Slots must be unique among"
                        " enabled peers."
                    }
                )

            check_overlap(enabled_cidrs)
            if "auto_ip_assignment" in validated_data:
                locked_interface.auto_ip_assignment = validated_data[
                    "auto_ip_assignment"
                ]
            locked_interface.last_modified = timezone.now()
            locked_interface.save()
        return locked_interface


class OwnerField(StringRelatedField):
    def to_representation(self, value: Player):
        return f"{value.username} <{value.email}>"


class KeySlotSerializer(ModelSerializer):
    owner = OwnerField()
    config_url = SerializerMethodField("get_config_url")

    class Meta:
        model = KeySlot
        read_only_fields = ("id", "owner", "managed", "config_url")
        fields = read_only_fields + ("name", "public_key")
        validators = (KeySlotValidator(),)

    def get_config_url(self, key_slot: KeySlot) -> str | None:
        if Peer.objects.filter(key_slot=key_slot, enabled=True).exists():
            return reverse(vpn_config_download, kwargs={"key_slot_id": key_slot.id})
        else:
            return None

    def create(self, validated_data):
        request = self.context["request"]
        owner = get_player_from_request(request)
        validated_data["owner_id"] = owner.id
        public_key = validated_data.get("public_key")
        # Ensure None is used instead of empty string
        validated_data["public_key"] = public_key or None
        return super().create(validated_data)

    def update(self, keyslot: KeySlot, validated_data):
        result = super().update(keyslot, validated_data)
        # TODO might be limited to actual key changes
        for peer in Peer.objects.filter(key_slot=keyslot, enabled=True).all():
            peer.interface.last_modified = timezone.now()
            peer.interface.save()
        return result
