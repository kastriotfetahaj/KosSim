__all__ = ["get_team_ifname", "try_resolve"]
import logging
import socket
from ipaddress import IPv4Address
from typing import assert_never

from ctfroute.defs import TEAM_IFNAME_PREFIX
from ctfroute.state.external import NetEntity, NetEntityId, TeamId
from ctfroute.state.internal import Team

LOGGER = logging.getLogger(__name__)


async def try_resolve(hostname: str) -> IPv4Address | None:
    """
    Try to resolve a hostname.

    Not really async, but we might swap socket.gethostbyname for an async dns
    implementation at some point.
    """
    try:
        return IPv4Address(socket.gethostbyname(hostname))
    except socket.gaierror:
        LOGGER.warning(f"Could not resolve '{hostname}'")
        return None


def get_team_ifname(team_id: str) -> str:
    return f"{TEAM_IFNAME_PREFIX}{team_id}"


NetEntityStore = dict[NetEntityId, NetEntity]
TeamStore = dict[TeamId, Team]


class RouterConnectivityDriverStateBase:
    def __init__(self, router_ip: IPv4Address):
        self.teams: TeamStore = {}
        self.net_entities: NetEntityStore = {}
        self.router_ip = router_ip

    def _get_store(self, entity: Team | NetEntity) -> TeamStore | NetEntityStore:
        if isinstance(entity, Team):
            return self.teams
        elif isinstance(entity, NetEntity):
            return self.net_entities
        else:
            assert_never(entity)

    def set(self, entity: Team | NetEntity) -> None:
        store = self._get_store(entity)
        # mypy doesn't get that the stores type depends on the entities type
        store[entity.id] = entity.model_copy(deep=True)  # type: ignore

    def get(self, entity: Team | NetEntity) -> Team | NetEntity:
        store = self._get_store(entity)
        return store[entity.id]

    def delete(self, entity: Team | NetEntity) -> None:
        store = self._get_store(entity)
        del store[entity.id]
