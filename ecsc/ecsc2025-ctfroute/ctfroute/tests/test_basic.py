import pytest
from pyroute2 import NDB

from ctfroute.defs import DEFAULT_MTU
from ctfroute.drivers.utils import get_team_ifname
from ctfroute.drivers.wireguard.driver import (
    WireguardTeamConnectivityDriver,
)
from ctfroute.drivers.wireguard.state import WireGuardTeamConnectivity


@pytest.mark.asyncio
async def test_create_wg_interfaces(test_ctfroute_conf, maybe_enter_namespace):
    teams = [
        team
        for team in test_ctfroute_conf.initial_state.teams
        if isinstance(team.connectivity, WireGuardTeamConnectivity)
    ]
    if_manager = WireguardTeamConnectivityDriver(mtu=DEFAULT_MTU)

    with NDB() as ndb:
        for team in teams:
            if_name = get_team_ifname(team.id)

            assert if_name not in ndb.interfaces
            await if_manager.sync(team)
            assert if_name in ndb.interfaces


@pytest.mark.asyncio
async def test_delete_wg_interfaces(test_ctfroute_conf, maybe_enter_namespace):
    teams = [
        team
        for team in test_ctfroute_conf.initial_state.teams
        if isinstance(team.connectivity, WireGuardTeamConnectivity)
    ]
    if_manager = WireguardTeamConnectivityDriver(mtu=DEFAULT_MTU)
    # Create interfaces
    with NDB() as ndb:
        for team in teams:
            if_name = get_team_ifname(team.id)

            await if_manager.sync(team)
            assert if_name in ndb.interfaces

            await if_manager.teardown(team)
            assert if_name not in ndb.interfaces
