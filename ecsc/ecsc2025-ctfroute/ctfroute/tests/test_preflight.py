import asyncio
import json
from itertools import combinations, permutations
from typing import AsyncIterator, TypeVar

import pytest

from ctfroute.adapters.yaml_conf import YamlConfig
from ctfroute.utils import ping
from ctftest.agent.client import VulnboxesClient
from ctftest.agent.ctftest_pb2 import (
    ListenStatus,
)


@pytest.mark.preflight
@pytest.mark.asyncio
async def test_orga_to_vulnbox_ping(
    max_vulnboxes, integration_ctfroute_conf: YamlConfig
):
    all_teams = [
        team
        for idx, team in enumerate(integration_ctfroute_conf.initial_state.teams)
        if not max_vulnboxes or idx < max_vulnboxes
    ]
    for team in all_teams:
        success = await ping(team.vulnbox)
        assert success


@pytest.mark.parametrize("src,tgt", permutations(range(1, 3), 2))
@pytest.mark.asyncio
@pytest.mark.preflight
async def test_ping_between_boxes(integration_ctfroute_client, src, tgt):
    async with integration_ctfroute_client as client:
        result = await client.vulnbox_ping(src, tgt)
        assert result.success


@pytest.mark.parametrize("src,dst", list(permutations(range(1, 3), 2)))
@pytest.mark.asyncio
@pytest.mark.preflight
async def test_iperf_between_boxes(
    integration_ctfroute_client: VulnboxesClient, src: int, dst: int, max_vulnboxes
):
    async with integration_ctfroute_client as client:
        server_events = client.vulnbox_iperf_server(dst, port=1234, duration=3)
        server_event = await anext(server_events)
        assert server_event.status == ListenStatus.READY

        client_events = client.vulnbox_iperf_client(src, dst, port=1234, duration=2)
        client_event = await anext(client_events)
        assert client_event.status == ListenStatus.READY

        server_event = await anext(server_events)
        assert server_event.status == ListenStatus.DONE

        client_event = await anext(client_events)
        assert client_event.status == ListenStatus.DONE

        server_stats = json.loads(server_event.json)
        client_stats = json.loads(client_event.json)

        # TODO: ADD SLA assertions?
        assert len(server_stats["start"]["connected"]) == 1
        assert len(client_stats["start"]["connected"]) == 1


T = TypeVar("T")


async def gather_streams(streams: list[AsyncIterator[T]]) -> list[T]:
    return await asyncio.gather(*(anext(stream) for stream in streams))


@pytest.mark.preflight
@pytest.mark.asyncio
async def test_simultaneous_iperf(
    integration_ctfroute_client: VulnboxesClient,
    integration_ctfroute_conf: YamlConfig,
    max_vulnboxes: int | None,
):
    all_teams = [
        team.id
        for idx, team in enumerate(integration_ctfroute_conf.initial_state.teams)
        if not max_vulnboxes or idx < max_vulnboxes
    ]
    async with integration_ctfroute_client as client:
        server_streams = []
        for team in all_teams:
            server_stream = client.vulnbox_iperf_server(team, port=1235, duration=10)
            server_streams.append(server_stream)

        for server_event in await gather_streams(server_streams):
            assert server_event.status == ListenStatus.READY

        client_streams = []
        for src, dst in combinations(all_teams, 2):
            client_stream = client.vulnbox_iperf_client(src, dst, port=1235, duration=5)
            client_streams.append(client_stream)

        for client_event in await gather_streams(client_streams):
            assert client_event.status == ListenStatus.READY

        for server_event in await gather_streams(server_streams):
            assert server_event.status == ListenStatus.DONE
            server_stats = json.loads(server_event.json)
            print(server_stats)
            assert len(server_stats["start"]["connected"]) == 1

        for client_event in await gather_streams(client_streams):
            assert client_event.status == ListenStatus.DONE
            client_stats = json.loads(client_event.json)
            print(client_stats)
            assert len(client_stats["start"]["connected"]) == 1


@pytest.mark.preflight
@pytest.mark.asyncio
async def test_canary_gateway(
    integration_ctfroute_client: VulnboxesClient,
    integration_ctfroute_conf: YamlConfig,
    max_vulnboxes: int | None,
):
    all_teams = [
        team
        for idx, team in enumerate(integration_ctfroute_conf.initial_state.teams)
        if not max_vulnboxes or idx < max_vulnboxes
    ]
    for team in all_teams:
        gateway = str(team.gateway)
        # TODO: check access for gateway and dataplane with modified wg conf
        _gateway_data_plane = f"10.232.{team.id}.{10 + int(team.id)}"
        _gateway_overlay = f"10.233.{team.id}.{10 + int(team.id)}"
        url = f"http://{gateway}:2113"
        success = await integration_ctfroute_client.vulnbox_get_request(team.id, url)
        assert success.status_code == 200
        assert b"You should see this!" in success.body
        success = await integration_ctfroute_client.vulnbox_get_request(team.id, url)
        url = f"http://{gateway}:2114"
        success = await integration_ctfroute_client.vulnbox_get_request(team.id, url)
        assert success.status_code == 0
