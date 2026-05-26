from datetime import datetime
from logging import getLogger

from constance import config
from django.db.models import F, Q
from django.http import HttpRequest
from rest_framework.decorators import api_view, permission_classes
from rest_framework.generics import ListAPIView, RetrieveUpdateAPIView
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response

from mainpage.models import Interface, Peer
from mainpage.views.api.router.serializers import (
    InterfaceDetailSerializer,
    InterfacesSerializer,
    TestConfigSerializer,
)

AUTH_HEADER = "X-API-TOKEN"
LOGGER = getLogger(__name__)


class SuperUserOrRouter(BasePermission):
    def has_permission(self, request: HttpRequest, view):
        if AUTH_HEADER in request.headers and config.ROUTER_TOKEN:
            return request.headers.get(AUTH_HEADER) == config.ROUTER_TOKEN
        elif request.user.is_authenticated and request.user.is_superuser:
            return True
        return False


class InterfacesView(ListAPIView):
    serializer_class = InterfacesSerializer
    permission_classes = (SuperUserOrRouter,)

    def get_queryset(self):
        queryset = Interface.objects.prefetch_related("team").all()
        if "need_sync" in self.request.GET:
            queryset = queryset.filter(
                Q(last_modified__gt=F("last_synced")) | Q(last_synced__isnull=True)
            )
        return queryset


class InterfaceDetailView(RetrieveUpdateAPIView):
    serializer_class = InterfaceDetailSerializer
    queryset = Interface.objects.prefetch_related("team").all()
    permission_classes = (SuperUserOrRouter,)
    lookup_field = "team__team_id"
    lookup_url_kwarg = "pk"


@api_view(["POST"])
@permission_classes((SuperUserOrRouter,))
def sync_interface(request: Request, pk: int):
    try:
        version = request.data["version"]
        version_date = datetime.fromisoformat(version)
    except (KeyError, ValueError):
        LOGGER.exception("Bad sync request")
        return Response(status=400)

    Interface.objects.filter(team__team_id=pk).update(last_synced=version_date)
    return Response(status=200, data={"message": "OK"})


@api_view(["GET"])
@permission_classes((SuperUserOrRouter,))
def get_test_configs(request: Request):
    peers = Peer.objects.filter(type=Peer.TypeChoices.TESTING)
    serializer = TestConfigSerializer(peers, many=True)
    return Response(status=200, data=serializer.data)
