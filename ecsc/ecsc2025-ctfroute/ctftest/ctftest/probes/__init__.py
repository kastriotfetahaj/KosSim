import asyncio
from asyncio import (
    Server,
    StreamReader,
    StreamWriter,
    new_event_loop,
    set_event_loop,
    start_server,
)
from ipaddress import IPv4Address
from logging import getLogger
from time import monotonic
from typing import AsyncGenerator, NamedTuple

from scapy.config import conf
from scapy.layers.inet import ICMP, IP
from scapy.sendrecv import sr1

DEFAULT_TIMEOUT = 3


logger = getLogger(__name__)


def icmp_probe(address: IPv4Address, retries: int, timeout: int | None) -> bool:
    src_interface, *_ = conf.route.route(str(address))
    packet = IP(src=conf.ifaces[src_interface].ip, dst=str(address)) / ICMP()
    reply = sr1(
        packet, retry=retries, timeout=timeout or DEFAULT_TIMEOUT, verbose=False
    )
    return reply is not None and reply.type == 0 and reply.src == str(address)


class EchoServer:
    class Result(NamedTuple):
        client_addr: str | None
        client_port: int | None
        amount: int
        data: bytes
        duration: float

    def __init__(
        self, port: int, echo: bool = False, collect: bool = False, amount: int = 0
    ):
        self.port = port
        self.echo = echo
        self.collect = collect
        self.recv = 0
        self.recv_max = amount
        self.data = b""
        self.server: Server | None = None
        self.client: tuple[str | None, int | None] = None, None
        self.start_time: float = 0
        self.end_time: float = 0
        self.read_timeout: float = 1
        self.listen_timeout: float = 2

    async def client_connected(self, reader: StreamReader, writer: StreamWriter):
        assert self.server is not None
        if self.client[0] is not None:
            writer.write_eof()
            writer.close()
            return

        self.start_time = monotonic()
        self.client = writer.transport.get_extra_info("peername")
        assert self.client is not None

        while self.recv_max == 0 or self.recv < self.recv_max:
            try:
                async with asyncio.timeout(self.read_timeout):
                    if self.recv_max > 0:
                        chunk = await reader.read(self.recv_max - self.recv)
                    else:
                        chunk = await reader.read()
            except TimeoutError:
                break
            if len(chunk) == 0:
                break
            if self.collect:
                self.data += chunk
            self.recv += len(chunk)
            if self.echo:
                writer.write(chunk)

        writer.write_eof()
        await writer.drain()
        writer.close()

        await writer.wait_closed()
        self.end_time = monotonic()
        self.server.close()

    def abort_if_no_connection(self):
        assert self.server is not None
        if self.client[0] is None:
            logger.warning(
                f"No client connected after {self.listen_timeout} seconds. Closing server."
            )
            self.server.close()

    async def run(self):
        self.server = await start_server(
            self.client_connected,
            host=None,
            port=self.port,
        )
        loop = asyncio.get_event_loop()
        loop.call_later(self.listen_timeout, self.abort_if_no_connection)
        await self.server.start_serving()

    def get_result(self):
        assert self.server
        assert not self.server.is_serving()
        assert self.client is not None
        return self.Result(
            client_addr=self.client[0],
            client_port=self.client[1],
            data=self.data,
            amount=self.recv,
            duration=self.end_time - self.start_time,
        )


async def tcp_listen(
    port: int, echo: bool, collect: bool, amount: int
) -> AsyncGenerator[None | EchoServer.Result]:
    server = EchoServer(port, echo=echo, collect=collect, amount=amount)
    await server.run()
    yield None
    assert server.server is not None
    await server.server.wait_closed()
    yield server.get_result()


async def tcp_send(
    target: str, port: int, message: bytes, echo_recv: bool, connect_timeout: int
) -> tuple[str | None, float, bytes]:
    response = b""
    start_timer = monotonic()
    mode = "Connect"
    try:
        async with asyncio.timeout(connect_timeout):
            reader, writer = await asyncio.open_connection(target, port)
        mode = "Write"
        writer.write(message)
        writer.write_eof()
        await writer.drain()
        if echo_recv:
            mode = "Read"
            response = await reader.read(len(message))
        writer.close()
        mode = "Close"
        await writer.wait_closed()
        end_timer = monotonic()
        duration = end_timer - start_timer
        return None, duration, response
    except TimeoutError:
        end_timer = monotonic()
        duration = end_timer - start_timer
        return f"{mode} timeout", duration, b""


async def main():
    server = EchoServer(2000, echo=True)
    print(await server.run())


if __name__ == "__main__":
    loop = new_event_loop()
    set_event_loop(loop)
    loop.run_until_complete(main())
