import asyncio
import logging
import uuid
from argparse import ArgumentParser
from asyncio import new_event_loop, set_event_loop
from asyncio.subprocess import Process
from functools import wraps
from ipaddress import IPv4Address
from typing import AsyncGenerator

import aiohttp
import grpc
import scapy.utils
from scapy.sendrecv import AsyncSniffer

from ctfroute.debug import add_debug_flags, setup_debugging
from ctfroute.utils import setup_logging
from ctftest.agent import ctftest_pb2, ctftest_pb2_grpc
from ctftest.agent.ctftest_pb2 import ListenStatus
from ctftest.probes import icmp_probe, tcp_listen, tcp_send
from ctftest.sniffer import sniff

# Coroutines to be invoked when the event loop is shutting down.
_cleanup_coroutines = []

LOGGER = logging.getLogger(__name__)


class SubprocessContext:
    def __init__(self, *args, **kwargs):
        self._args = args
        self._kwargs = kwargs
        self._process: Process | None = None

    async def __aenter__(self):
        LOGGER.debug(f"Entering context: Starting subprocess {self._args}...")
        self._process = await asyncio.create_subprocess_exec(
            *self._args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **self._kwargs,
        )
        return self._process

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        _ = (exc_type, exc_val, exc_tb)
        LOGGER.debug("Exiting context: Checking subprocess state...")
        assert self._process is not None
        if self._process.returncode is None:
            LOGGER.debug("Subprocess is still running. Terminating...")
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except (asyncio.TimeoutError, ProcessLookupError):
                LOGGER.warning("Graceful termination failed. Forcibly killing...")
                try:
                    self._process.kill()
                    await asyncio.wait_for(self._process.wait(), timeout=5)
                except (asyncio.TimeoutError, ProcessLookupError):
                    LOGGER.warning("Force kill timed out...")
            finally:
                LOGGER.debug(
                    f"Subprocess exited with return code: {self._process.returncode}"
                )
        else:
            LOGGER.debug(
                f"Subprocess already exited with code: {self._process.returncode}"
            )


def log_errors(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except:
            LOGGER.exception("An Error has occured")
            raise

    return wrapper


class Agent(ctftest_pb2_grpc.CtfTestAgentServicer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sniffer_sessions: dict[str, AsyncSniffer] = dict()

    async def ping(
        self,
        request: ctftest_pb2.PingRequest,
        context: grpc.aio.ServicerContext,
    ) -> ctftest_pb2.PingResponse:
        _ = context
        LOGGER.info(f"Pinging {IPv4Address(request.target)}")
        result = icmp_probe(
            address=IPv4Address(request.target),
            retries=request.retries,
            timeout=request.timeout,
        )
        return ctftest_pb2.PingResponse(success=result)

    async def sniff(
        self, request: ctftest_pb2.StartSniffRequest, context: grpc.aio.ServicerContext
    ) -> ctftest_pb2.StartSniffResponse:
        _ = context
        session_id = str(uuid.uuid4())
        LOGGER.info(f"Starting sniff session {session_id}")

        sniffer = await sniff(filter=request.filter, timeout=request.seconds)

        self._sniffer_sessions[session_id] = sniffer
        return ctftest_pb2.StartSniffResponse(uuid=session_id)

    async def stopSniff(
        self, request: ctftest_pb2.StopSniffRequest, context: grpc.aio.ServicerContext
    ) -> ctftest_pb2.StopSniffResponse:
        _ = context
        LOGGER.info(f"Stopping sniff {request.uuid}")

        sniffer = self._sniffer_sessions[request.uuid]
        if sniffer.running:
            sniffer.stop(join=True)
            status = ctftest_pb2.SniffStatus.STOPPED_MANUALLY
        else:
            status = ctftest_pb2.SniffStatus.STOPPED_BY_LIMIT

        assert sniffer.results is not None
        scapy.utils.wrpcapng(f"/tmp/{request.uuid}.pcap", sniffer.results)

        return ctftest_pb2.StopSniffResponse(status=status)

    async def getSniffRecording(
        self,
        request: ctftest_pb2.SniffRecordingRequest,
        context: grpc.aio.ServicerContext,
    ) -> ctftest_pb2.SniffRecordingResponse:
        _ = context
        LOGGER.info(f"getting sniff recording {request.uuid}")
        with open(f"/tmp/{request.uuid}.pcap", "rb") as f:
            pcap_bytes = f.read()
        return ctftest_pb2.SniffRecordingResponse(recording=pcap_bytes)

    async def listen(
        self,
        request: ctftest_pb2.ListenRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncGenerator[ctftest_pb2.ListenResponse]:
        _ = context
        LOGGER.info(f"Receiving on {request.port} Echoing: {request.echo}.")

        from ctftest.sniffer import sniff

        sniffer = await sniff(filter=f"tcp and port {request.port}")

        gen = tcp_listen(
            request.port,
            echo=request.echo,
            collect=request.collect,
            amount=request.amount,
        )
        assert await anext(gen) is None
        yield ctftest_pb2.ListenResponse(
            status=ListenStatus.READY,
        )
        result = await anext(gen)
        assert result is not None

        sniffer_results = sniffer.stop(join=True)
        LOGGER.info("Sniffed packets:")
        for packet in sniffer_results:
            LOGGER.info(f"{packet}")

        yield ctftest_pb2.ListenResponse(
            status=ListenStatus.DONE,
            client=result.client_addr,
            src_port=result.client_port,
            amount=result.amount,
            message=result.data,
            duration=result.duration,
        )

    async def iperf(
        self, request: ctftest_pb2.IperfRequest, context: grpc.aio.ServicerContext
    ) -> AsyncGenerator[ctftest_pb2.IperfResponse]:
        _ = context
        if request.server:
            LOGGER.info(
                f"Running iperf server, binding to {request.address}:{request.port}"
            )
            cmd = [
                "iperf3",
                "--one-off",
                "--server",
                "--bind",
                request.address,
                "--port",
                str(request.port),
                "--json",
            ]
        else:
            LOGGER.info(
                f"Running iperf client, connecting to {request.address}:{request.port}"
            )
            cmd = [
                "iperf3",
                "--connect-timeout",
                "1000",  # Timeout is in ms!
                "--time",
                str(request.duration),
                "--client",
                request.address,
                "--port",
                str(request.port),
                "--json",
            ]

        async with asyncio.timeout(request.duration + 5):
            async with SubprocessContext(*cmd) as process:
                yield ctftest_pb2.IperfResponse(status=ListenStatus.READY)
                stdout, _ = await process.communicate()

        yield ctftest_pb2.IperfResponse(status=ListenStatus.DONE, json=stdout.decode())

    async def send(
        self, request: ctftest_pb2.SendRequest, context: grpc.aio.ServicerContext
    ) -> ctftest_pb2.SendResponse:
        _ = context
        LOGGER.info(
            f"Sending to {request.target}:{request.port} Bytes: {len(request.message)} Receive echo: {request.echo_recv}."
        )
        status, duration, response = await tcp_send(
            target=request.target,
            port=request.port,
            message=request.message,
            echo_recv=request.echo_recv,
            connect_timeout=request.connect_timeout,
        )

        success = status is None
        return ctftest_pb2.SendResponse(
            success=success, duration=duration, response=response, status=status
        )

    async def httpGet(
        self, request: ctftest_pb2.HttpGet, context: grpc.aio.ServicerContext
    ) -> ctftest_pb2.HttpResponse:
        _ = context
        LOGGER.info(f"Sending HTTP request to {request.url}")
        timeout = aiohttp.ClientTimeout(total=request.timeout)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(request.url) as resp:
                    body = await resp.read()
                    return ctftest_pb2.HttpResponse(status_code=resp.status, body=body)
        except asyncio.TimeoutError:
            return ctftest_pb2.HttpResponse(status_code=0, body=b"")


async def serve() -> None:
    server = grpc.aio.server()
    ctftest_pb2_grpc.add_CtfTestAgentServicer_to_server(Agent(), server)
    listen_addr = "0.0.0.0:50051"
    server.add_insecure_port(listen_addr)
    LOGGER.info(f"Starting testing agent on {listen_addr}")
    await server.start()

    async def server_graceful_shutdown():
        LOGGER.info("Starting graceful shutdown...")
        await server.stop(5)

    _cleanup_coroutines.append(server_graceful_shutdown())
    await server.wait_for_termination()


def cli_main():
    parser = ArgumentParser("CTFTest Agent")
    add_debug_flags(parser)
    args = parser.parse_args()

    setup_logging()
    loop = new_event_loop()
    set_event_loop(loop)

    setup_debugging(args, loop)

    try:
        loop.run_until_complete(serve())
    finally:
        loop.run_until_complete(*_cleanup_coroutines)
        loop.close()


if __name__ == "__main__":
    cli_main()
