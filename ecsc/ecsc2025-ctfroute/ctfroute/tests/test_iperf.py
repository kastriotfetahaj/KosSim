import asyncio
import json
from itertools import permutations
from typing import AsyncIterator, TypeVar

import pytest

from ctftest.agent.ctftest_pb2 import (
    ListenStatus,
)


@pytest.mark.parametrize("src,dst", list(permutations(range(1, 5), 2)))
@pytest.mark.asyncio
@pytest.mark.integration
async def test_iperf_between_boxes(integration_ctfroute_client, src, dst):
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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_simultaneous_iperf(
    integration_ctfroute_client, integration_ctfroute_conf
):
    all_teams = [team.id for team in integration_ctfroute_conf.initial_state.teams]
    async with integration_ctfroute_client as client:
        server_streams = []
        for team in all_teams:
            server_stream = client.vulnbox_iperf_server(team, port=1235, duration=10)
            server_streams.append(server_stream)

        for server_event in await gather_streams(server_streams):
            assert server_event.status == ListenStatus.READY

        client_streams = []
        for src, dst in zip(all_teams, all_teams[::-1]):
            client_stream = client.vulnbox_iperf_client(src, dst, port=1235, duration=5)
            client_streams.append(client_stream)

        for client_event in await gather_streams(client_streams):
            assert client_event.status == ListenStatus.READY

        for server_event in await gather_streams(server_streams):
            assert server_event.status == ListenStatus.DONE
            server_stats = json.loads(server_event.json)
            assert len(server_stats["start"]["connected"]) == 1

        for client_event in await gather_streams(client_streams):
            assert client_event.status == ListenStatus.DONE
            client_stats = json.loads(client_event.json)
            assert len(client_stats["start"]["connected"]) == 1
