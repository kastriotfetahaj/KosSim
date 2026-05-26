from ipaddress import IPv4Address
from typing import AsyncGenerator, cast

import grpc
from grpc.aio import Channel

from ctfroute.state import external, internal
from ctftest.agent import ctftest_pb2, ctftest_pb2_grpc


class VulnboxesClient:
    def __init__(self, state: external.CtfRouteState):
        self.state = internal.CtfRouteState.from_initial(state)
        # Lazily opened rpc channels
        self.channels: dict[int, Channel] = {}

    async def __aenter__(self):
        return self

    def __await__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # TODO: Exit all channels
        ...

    async def _get_vulnbox_ip(self, vulnbox: int) -> IPv4Address | None:
        team = self.state.teamsById[str(vulnbox)]
        return team.vulnbox

    async def _get_vulnbox_endpoint(self, vulnbox: int) -> str:
        team = self.state.teamsById[str(vulnbox)]
        if "ctftest/endpoint" in team.meta:
            ctftest_endpoint = cast(str, team.meta["ctftest/endpoint"])
        else:
            ip = await self._get_vulnbox_ip(vulnbox)
            ctftest_endpoint = f"{ip}:50051"
        return ctftest_endpoint

    async def _get_channel(self, vulnbox: int) -> Channel:
        if vulnbox in self.channels:
            return self.channels[vulnbox]

        endpoint = await self._get_vulnbox_endpoint(vulnbox)
        channel = await grpc.aio.insecure_channel(endpoint).__aenter__()
        self.channels[vulnbox] = channel
        return channel

    async def _get_stub(self, vulnbox: int):
        # TODO: Maybe store stubs instead of channels?
        channel = await self._get_channel(vulnbox)
        return ctftest_pb2_grpc.CtfTestAgentStub(channel)

    async def vulnbox_ping(self, src: int, dest: int) -> ctftest_pb2.PingResponse:
        dest_ip = await self._get_vulnbox_ip(dest)
        assert dest_ip is not None
        stub = await self._get_stub(src)
        response: ctftest_pb2.PingResponse = await stub.ping(
            ctftest_pb2.PingRequest(
                target=str(dest_ip),
                retries=3,
                timeout=3,
            ),
        )
        return response

    async def vulnbox_tcp_recv(
        self,
        src: int,
        port: int,
        echo: bool = False,
        collect: bool = False,
        amount: int = 0,
    ) -> AsyncGenerator[ctftest_pb2.ListenResponse]:
        stub = await self._get_stub(src)
        listen_results = stub.listen(
            ctftest_pb2.ListenRequest(
                port=port, echo=echo, collect=collect, amount=amount
            )
        )
        async for res in listen_results:
            yield res

    async def vulnbox_tcp_send(
        self,
        src: int,
        dest: int,
        port: int,
        message: bytes,
        echo_recv: bool = False,
        echo_collect: bool = False,
        connect_timeout: int = 3,
    ) -> ctftest_pb2.SendResponse:
        dest_ip = await self._get_vulnbox_ip(dest)
        assert dest_ip is not None
        stub = await self._get_stub(src)
        response: ctftest_pb2.SendResponse = await stub.send(
            ctftest_pb2.SendRequest(
                target=str(dest_ip),
                port=port,
                message=message,
                echo_recv=echo_recv,
                echo_collect=echo_collect,
                connect_timeout=connect_timeout,
            ),
        )
        return response

    async def vulnbox_get_request(
        self, src: int, url: str, request_timeout: int = 5
    ) -> ctftest_pb2.HttpResponse:
        stub = await self._get_stub(src)
        response: ctftest_pb2.HttpResponse = await stub.httpGet(
            ctftest_pb2.HttpGet(url=url, timeout=request_timeout)
        )
        return response

    async def vulnbox_iperf_client(
        self, src: int, dst: int, port: int, duration: int
    ) -> AsyncGenerator[ctftest_pb2.IperfResponse]:
        dest_ip = await self._get_vulnbox_ip(dst)
        assert dest_ip is not None
        stub = await self._get_stub(src)
        results = stub.iperf(
            ctftest_pb2.IperfRequest(
                address=str(dest_ip), port=port, server=False, duration=duration
            )
        )
        async for res in results:
            yield res

    async def vulnbox_iperf_server(
        self, src: int, port: int, duration: int, bind: str = "0.0.0.0"
    ) -> AsyncGenerator[ctftest_pb2.IperfResponse]:
        stub = await self._get_stub(src)
        results = stub.iperf(
            ctftest_pb2.IperfRequest(
                address=bind, port=port, server=True, duration=duration
            )
        )
        async for res in results:
            yield res

    async def start_sniff(
        self, box: int, filter: str, seconds: int = 0
    ) -> ctftest_pb2.StartSniffResponse:
        stub = await self._get_stub(box)
        sniff_results: ctftest_pb2.StartSniffResponse = await stub.sniff(
            ctftest_pb2.StartSniffRequest(filter=filter, seconds=seconds)
        )
        return sniff_results

    async def stop_sniff(self, box: int, uuid: str) -> ctftest_pb2.StopSniffResponse:
        stub = await self._get_stub(box)
        sniff_results: ctftest_pb2.StopSniffResponse = await stub.stopSniff(
            ctftest_pb2.StopSniffRequest(uuid=uuid)
        )
        return sniff_results

    async def get_sniff_recording(
        self, box: int, uuid: str
    ) -> ctftest_pb2.SniffRecordingResponse:
        stub = await self._get_stub(box)
        recording_results: ctftest_pb2.SniffRecordingResponse = (
            await stub.getSniffRecording(ctftest_pb2.SniffRecordingRequest(uuid=uuid))
        )
        return recording_results
