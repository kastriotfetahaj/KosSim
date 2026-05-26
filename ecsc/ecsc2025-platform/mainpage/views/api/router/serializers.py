from typing import cast

from constance import config
from django.db.models import Prefetch
from django.utils import timezone
from rest_framework.serializers import ModelSerializer, SerializerMethodField

from mainpage.models import Interface, KeySlot, Peer
from mainpage.network_lib import get_team_vpn_port


class KeySlotSerializer(ModelSerializer):
    class Meta:
        model = KeySlot
        read_only_fields = ("public_key",)
        fields = read_only_fields


class PeerSerializer(ModelSerializer):
    key_slot = KeySlotSerializer()

    class Meta:
        model = Peer
        read_only_fields = ("key_slot", "cidr")
        fields = read_only_fields


class InterfacesSerializer(ModelSerializer):
    """Used to "list" interfaces, therefore minimal return value."""

    id = SerializerMethodField("get_id")

    class Meta:
        model = Interface
        read_only_fields = ("id",)
        fields = read_only_fields

    def get_id(self, interface: Interface):
        return interface.team.team_id


class InterfaceDetailSerializer(ModelSerializer):
    port = SerializerMethodField("get_port")
    peers = SerializerMethodField("get_peers")
    id = SerializerMethodField("get_id")

    # Only prefetch and show peers are enabled and have a public key set in their keyslot
    _peer_filter = dict(enabled=True, key_slot__public_key__isnull=False)
    queryset = Interface.objects.prefetch_related(
        Prefetch("peers", queryset=Peer.objects.filter(**_peer_filter)),
    )

    class Meta:
        model = Interface
        read_only_fields = ("id", "last_modified", "cidr", "port", "peers")
        fields = ("public_key",) + read_only_fields

    def get_id(self, interface: Interface):
        return interface.team.team_id

    def get_port(self, interface: Interface) -> int:
        team_id = cast(int, interface.team.team_id)
        return get_team_vpn_port(team_id)

    def get_peers(self, interface: Interface):
        serializer = PeerSerializer(
            interface.peers.filter(**self._peer_filter), many=True
        )  # type: ignore
        return serializer.data

    def update(self, instance: Interface, validated_data):
        instance.public_key = validated_data.get("public_key")
        instance.last_modified = timezone.now()
        instance.save()
        return instance


class TestPeerSerializer(ModelSerializer):
    public_key = SerializerMethodField("get_public_key")
    endpoint = SerializerMethodField("get_endpoint")
    allowed_ips = SerializerMethodField("get_allowed_ips")

    class Meta:
        model = Interface
        read_only_fields = ("public_key", "endpoint", "allowed_ips")
        fields = read_only_fields

    def get_public_key(self, interface: Interface):
        return interface.public_key

    def get_endpoint(self, interface: Interface):
        port = get_team_vpn_port(cast(int, interface.team.team_id))
        return f"{config.VPN_HOST}:{port}"

    def get_allowed_ips(self, interface: Interface):
        return "10.32.0.0/15"


class TestConfigSerializer(ModelSerializer):
    id = SerializerMethodField("get_id")
    private_key = SerializerMethodField("get_private_key")
    address = SerializerMethodField("get_address")
    peers = SerializerMethodField("get_peers")

    class Meta:
        model = Peer
        read_only_fields = ("id", "private_key", "address", "peers")
        fields = read_only_fields

    def get_id(self, peer: Peer):
        return peer.interface.team.team_id

    def get_private_key(self, peer: Peer):
        return peer.key_slot.private_key

    def get_address(self, peer: Peer):
        return peer.cidr

    def get_peers(self, peer: Peer):
        return [TestPeerSerializer(peer.interface).data]
