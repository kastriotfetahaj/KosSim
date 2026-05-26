from typing import cast

from django.core.exceptions import PermissionDenied as DjangoPermDenied
from django.db import transaction
from django.utils import timezone
from rest_framework import permissions
from rest_framework.exceptions import NotAuthenticated, PermissionDenied
from rest_framework.generics import (
    CreateAPIView,
    GenericAPIView,
    ListAPIView,
    RetrieveUpdateDestroyAPIView,
)
from rest_framework.mixins import (
    RetrieveModelMixin,
    UpdateModelMixin,
)
from rest_framework.request import Request
from rest_framework.response import Response

from mainpage.models import Interface, KeySlot, Peer, Player, TeamProfile
from mainpage.network_lib import assign_next_free_ip_address
from mainpage.utils import get_player_from_request
from mainpage.views.api.player.serializers import InterfaceSerializer, KeySlotSerializer


class DoNotChangeManaged(permissions.BasePermission):
    def has_object_permission(self, request, view, obj: KeySlot):
        return not obj.managed or request.method in permissions.SAFE_METHODS


class InterfaceView(GenericAPIView, RetrieveModelMixin, UpdateModelMixin):
    serializer_class = InterfaceSerializer
    permission_classes = (DoNotChangeManaged,)

    def get_queryset(self):
        try:
            player = get_player_from_request(self.request)
        except DjangoPermDenied as e:
            raise NotAuthenticated from e

        if not player.is_at_least_technician:
            raise PermissionDenied

        return Interface.objects.filter(team=player.team)

    def get_object(self):
        return self.get_queryset().get()

    def get(self, request, *args, **kwargs):
        return self.retrieve(request, *args, **kwargs)

    def put(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)


class KeySlotQuerySetMixin(GenericAPIView):
    serializer_class = KeySlotSerializer

    def check_permissions(self, request):
        if request.method not in permissions.SAFE_METHODS:
            try:
                player = get_player_from_request(self.request)
            except DjangoPermDenied as e:
                raise NotAuthenticated from e
            if player.team.interface.managed:
                raise PermissionDenied

    def get_queryset(self):
        try:
            player = get_player_from_request(self.request)
        except DjangoPermDenied as e:
            raise NotAuthenticated from e

        if player.role in (Player.RoleChoices.CAPTAIN, Player.RoleChoices.TECHNICIAN):
            filter_args = {"owner__team": player.team}
        elif player.role == Player.RoleChoices.PLAYER:
            filter_args = {"owner": player}
        else:
            raise PermissionDenied

        return KeySlot.objects.filter(**filter_args)


class KeySlotView(KeySlotQuerySetMixin, RetrieveUpdateDestroyAPIView):
    permission_classes = (DoNotChangeManaged,)

    @transaction.atomic
    def update(self, request: Request, *args, **kwargs) -> Response:
        needs_sync = False
        had_public_key = bool(self.get_object().public_key)
        result = super().update(request, *args, **kwargs)
        key_slot: KeySlot = self.get_object()
        team: TeamProfile | None = None
        interface: Interface | None = None

        # if we set the public key for first time then auto-assign an IP to it
        if not had_public_key and key_slot.public_key:
            team = cast(Player, key_slot.owner).team
            interface = Interface.objects.get(team=team)
            if interface.auto_ip_assignment:
                needs_sync = assign_next_free_ip_address(team, interface, key_slot)

        # There is an enabled peer using this keyslot
        elif Peer.objects.filter(key_slot=key_slot, enabled=True).exists():
            needs_sync = True

        if needs_sync:
            team = team or cast(Player, key_slot.owner).team
            interface = interface or Interface.objects.get(team=team)
            interface.last_modified = timezone.now()
            interface.save()

        return result


class ListKeySlotsView(KeySlotQuerySetMixin, ListAPIView, CreateAPIView):
    @transaction.atomic
    def perform_create(self, serializer) -> None:
        super().perform_create(serializer)
        new_key_slot = serializer.instance
        if new_key_slot.public_key:
            team = new_key_slot.owner.team
            interface = Interface.objects.get(team=team)
            if interface.auto_ip_assignment:
                needs_sync = assign_next_free_ip_address(team, interface, new_key_slot)
                if needs_sync:
                    interface.last_modified = timezone.now()
                    interface.save()
