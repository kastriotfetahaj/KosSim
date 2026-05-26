import asyncio
import errno
import functools
import inspect
import ipaddress
import logging
import socket
import textwrap
import typing

from .types import AsyncConnection, IPAddress, IPVersion, IPNetwork


def merge_lines(string: str) -> str:
    '''Takes a string, dedents its, and joins its lines with spaces instead of newlines.'''
    return textwrap.dedent(string).strip().replace('\n', ' ')


def null_connection() -> AsyncConnection:
    '''Creates a connection that discards all written data, and reads nothing.'''
    class NullProtocol(asyncio.Protocol):
        pass

    class NullTransport(asyncio.Transport):
        def __init__(self):
            self._reading = True
            self._low = 1024
            self._high = 1024

        def is_closing(self) -> bool:
            return False
        def close(self):
            pass
        def set_protocol(self, protocol):
            assert isinstance(protocol, NullProtocol)
        def get_protocol(self):
            return NullProtocol()

        def is_reading(self):
            return self._reading
        def pause_reading(self):
            self._reading = False
        def resume_reading(self):
            self._reading = True

        def set_write_buffer_limits(self, high=None, low=None):
            match (low, high):
                case (None, None): return
                case (low,  None): self._low, self._high = low, max(self._high, low)
                case (None, high): self._low, self._high = min(self._low, high), high
                case (low,  high): self._low, self._high = min(low, high), max(low, high)
        def get_write_buffer_size(self):
            return self._low
        def get_write_buffer_limits(self):
            return (self._low, self._high)
        def write(self, data):
            _ = data
        def write_eof(self):
            pass
        def can_write_eof(self):
            return True
        def abort(self):
            pass

    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    reader.feed_eof()
    writer = asyncio.StreamWriter(NullTransport(), NullProtocol(), reader, loop)
    return (reader, writer)


_MakeServer: typing.TypeAlias = typing.Callable[
    typing.Concatenate[typing.Callable[[asyncio.StreamReader, asyncio.StreamWriter], None], ...],
    typing.Awaitable[asyncio.Server]
] # e.g. asyncio.start_server

async def accept_one_connection(make_server: _MakeServer, *args, **kwargs) -> tuple[IPAddress, int, typing.Awaitable[AsyncConnection]]:
    '''
    Accepts a single connection from a server created with `make_server`.
    Awaiting the result of this function will yield the host and port on
    which the server is listening, and another future which when awaited
    on will yield the actual connection.
    '''
    connection = asyncio.Future()

    def callback(reader, writer):
        if not connection.done():
            connection.set_result((reader, writer))
        server.close()

    server = await make_server(callback, *args, **kwargs)
    sockets = server.sockets
    assert sockets, 'Server has no sockets'
    host, port, *_ = sockets[0].getsockname()
    host = ipaddress.ip_address(host)

    async def make_cancellation_safe(future: typing.Awaitable[AsyncConnection]) -> AsyncConnection:
        try:
            return await future
        except asyncio.CancelledError:
            server.close()
            await server.wait_closed()
            raise

    return host, port, make_cancellation_safe(connection)


class PacketStreamReader(asyncio.StreamReader):
    def __init__(self):
        super().__init__()
        self._packets = asyncio.Queue()

    def feed_data(self, data: typing.Iterable[typing.SupportsIndex]) -> None:
        self._packets.put_nowait(data)

    async def readline(self):
        raise RuntimeError('Cannot (sanely) use `readline` on packeted data')

    async def readuntil(self, separator = b'\n'):
        raise RuntimeError('Cannot (sanely) use `readuntil` on packeted data')

    async def readexactly(self, n: int):
        raise RuntimeError('Cannot (sanely) use `readexactly` on packeted data')

    async def read(self, n: int = -1) -> bytes:
        packet = await self._packets.get()
        if n >= 0:
            return packet[:n]
        else:
            return packet


class PacketStreamTransport(asyncio.Transport):
    def __init__(self, dgram: asyncio.DatagramTransport):
        super().__init__()
        self._dgram = dgram
        self._packets = asyncio.Queue()

    def set_protocol(self, protocol):
        self._dgram.set_protocol(protocol)

    def get_protocol(self) -> asyncio.BaseProtocol:
        return self._dgram.get_protocol()

    def close(self):
        self._dgram.close()

    def is_closing(self):
        return self._dgram.is_closing()

    def write(self, data):
        self._dgram.sendto(data, None)

    def can_write_eof(self):
        return False

    def abort(self):
        self._dgram.abort()


class PacketStreamProtocol(asyncio.DatagramProtocol):
    def __init__(self, reader: PacketStreamReader):
        super().__init__()
        self._reader = reader
        self._transport = None
        self._waiter = asyncio.get_running_loop().create_future()

    def connection_made(self, transport):
        self._transport = transport

    def datagram_received(self, data, addr):
        self._reader.feed_data(data)

    def error_received(self, exc):
        self._reader.set_exception(exc)

    def connection_lost(self, exc):
        self._waiter.set_result(None)
        self._reader.feed_eof()

    async def _drain_helper(self):
        return # This connection is immediately drained, so do nothing

    def _get_close_waiter(self, stream):
        return self._waiter


async def open_udp_connection(sock: socket.socket, *, loop: asyncio.AbstractEventLoop | None = None) -> AsyncConnection:
    '''Creates an `AsyncConnection from a UDP socket'''
    if sock.type != socket.SOCK_DGRAM:
        raise ValueError('Cannot create a UDP connection from a non-UDP socket')
    try:
        sock.getpeername() # This must be a _connected_ UDP socket.
    except OSError as error:
        if error.errno != errno.ENOTCONN:
            raise
        raise ValueError('UDP socket is not connected (call `connect` on it first)')

    loop = loop if loop is not None else asyncio.get_running_loop()
    reader = PacketStreamReader()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: PacketStreamProtocol(reader),
        sock=sock
    )
    writer = asyncio.StreamWriter(PacketStreamTransport(transport), protocol, reader, loop=loop)
    return reader, writer


def generate_variants(wrapper: typing.Callable[[int], typing.Callable], variants: dict[int, typing.Sequence[typing.Any]]):
    '''Generates multiple variants with the provided arguments from a single template function'''
    def must_call_variant(*args, **kwargs):
        raise RuntimeError('You cannot call functions registered with @generate_variants directly.')
    def generate_variants_impl(function: typing.Callable):
        for key, arguments in variants.items():
            assert ... in arguments, 'You must have `...` in the argument sequence for all variants'
            ellipsis = arguments.index(...)
            head = arguments[:ellipsis]
            tail = arguments[ellipsis + 1:]

            @functools.wraps(function)
            async def curried(*args, _impl_variant_head = head, _impl_variant_tail = tail, **kwargs):
                return await function(*_impl_variant_head, *args, *_impl_variant_tail, **kwargs)

            # Don't try to inject the parameters here.
            sig = inspect.Signature.from_callable(curried)

            arg_names = list(sig.parameters)
            del arg_names[:len(head)]
            del arg_names[-len(tail):]

            sig = sig.replace(parameters=[sig.parameters[name] for name in arg_names])
            setattr(curried, '__signature__', sig)

            globals()[wrapper.__name__ + f'_autogenerated_{key}'] = wrapper(key)(curried)
        return functools.wraps(function)(must_call_variant)
    return generate_variants_impl


T = typing.TypeVar('T')

def extract_argument(function: typing.Callable, target_type: type[T]) -> typing.Callable[[typing.Sequence, dict], T]:
    '''Generates a function to extract a typed (annotated) argument in a decorator'''
    signature = inspect.Signature.from_callable(function)
    candidates = [
        (index, param)
        for index, param in enumerate(signature.parameters.values())
        if isinstance(param.annotation, type) and issubclass(param.annotation, target_type)
    ]
    if len(candidates) != 1:
        raise TypeError(f'Multiple candidate arguments when extracting an argument of type {target_type} from {function}')
    index, param = candidates[0]
    if param.default is not inspect._empty:
        raise TypeError(f'Cannot extract defaulted arguments while extracting an argument of type {target_type} from {function}')
    match param.kind:
        case inspect._ParameterKind.VAR_POSITIONAL:
            raise TypeError(f'*{param.name} (variadic) is not an extractable parameter')
        case inspect._ParameterKind.VAR_KEYWORD:
            raise TypeError(f'**{param.name} (variadic) is not an extractable parameter')
        case inspect._ParameterKind.POSITIONAL_ONLY:
            return lambda args, _, _impl_index=index: args[_impl_index]
        case inspect._ParameterKind.KEYWORD_ONLY:
            return lambda _, kwargs, _impl_keyword=param.name: kwargs[_impl_keyword]
        case inspect._ParameterKind.POSITIONAL_OR_KEYWORD:
            return lambda args, kwargs, _impl_index=index, _impl_keyword=param.name: args[_impl_index] if len(args) > _impl_index else kwargs[_impl_keyword]


def internet_checksum(data: bytearray | bytes | memoryview) -> int:
    '''Computes an IP/TCP/UDP checksum from data.'''
    checksum = 0
    for i in range(0, len(data), 2):
        raw = data[i:i + 2]
        raw = raw if len(raw) >= 2 else bytes(raw).ljust(2, b'\0')
        word = int.from_bytes(raw, 'big')
        checksum += word
        checksum = (checksum & 0xffff) + (checksum >> 16)
    while checksum > 0xffff:
        checksum = (checksum & 0xffff) + (checksum >> 16)
    return checksum ^ 0xffff


def update_checksum(checksum: int, *,
                    remove: typing.Iterable[bytearray | bytes | memoryview] | None = None,
                    add: typing.Iterable[bytearray | bytes | memoryview] | None = None) -> int:
    '''Updates an IP/TCP/UDP checksum.'''
    checksum = 0xffff ^ checksum
    if remove is not None:
        for item in remove:
            checksum += internet_checksum(item)
    if add is not None:
        for item in add:
            checksum += 0xffff ^ internet_checksum(item)
    while checksum > 0xffff:
        checksum = (checksum & 0xffff) + (checksum >> 16)
    return checksum ^ 0xffff


async def anonymize_traffic(packet: bytes, mtu: int, logger: logging.LoggerAdapter) -> bytes | None:
    '''Strips IP and TCP options from a packet, and filters non-TCP/UDP traffic out.'''
    # NOTE: Keep this in sync with service/client/client.py
    # Otherwise, the checker will be fingerprintable.

    def to_bytes(packet: bytes | bytearray | memoryview | None) -> bytes | None:
        if isinstance(packet, (bytearray, memoryview)):
            return bytes(packet)
        return packet

    def to_bytearray(packet: bytes | bytearray | memoryview) -> bytearray:
        if not isinstance(packet, bytearray):
            return bytearray(packet)
        return packet

    def strip_tcp(packet: bytes | bytearray, ip_version: IPVersion, tcp_offset: int) -> bytes | bytearray | None:
        '''Strips the TCP options'''
        if tcp_offset + 20 > len(packet):
            logger.warning(f'Dropping packet with incomplete TCP header during anonymization: {packet!r}')
            return None
        payload_offset = tcp_offset + (packet[tcp_offset + 12] >> 4) * 4
        if payload_offset <= tcp_offset + 20:
            return packet
        if payload_offset > len(packet):
            logger.warning(f'Dropping incomplete TCP packet during anonymization: {packet!r}')
            return None

        options_length = payload_offset - (tcp_offset + 20)
        tcp_length = len(packet) - tcp_offset

        # On TCP SYN packets, _set_ the MSS according to the MTU.
        tcp_syn = bool(packet[tcp_offset + 13] & 2)
        replacement = (b'\x02\x04' + (mtu - tcp_offset - 20).to_bytes(2)) if tcp_syn else b''
        new_offset = ((packet[tcp_offset + 12] & 0xf) | (((20 + len(replacement)) // 4) << 4))

        length_delta = len(replacement) - options_length

        checksum = update_checksum(
            int.from_bytes(packet[tcp_offset + 16:tcp_offset + 18]),
            remove = [
                packet[tcp_offset + 12:tcp_offset + 14], # Old offset
                packet[tcp_offset + 20:payload_offset], # Options
                tcp_length.to_bytes(2), # Old length
            ],
            add = [
                new_offset.to_bytes(1) + packet[tcp_offset + 13].to_bytes(1), # New offset
                replacement, # New options
                (tcp_length + length_delta).to_bytes(2), # New length
            ],
        )

        packet = to_bytearray(packet)
        packet[tcp_offset + 12] = new_offset
        packet[tcp_offset + 16:tcp_offset + 18] = checksum.to_bytes(2)
        packet[tcp_offset + 20:payload_offset] = replacement
        if ip_version == 4:
            # Must update IP header's total length and IP checksum
            packet[2:4] = (int.from_bytes(packet[2:4]) + length_delta).to_bytes(2)
            packet[10:12] = b'\0\0' # Clear checksum
            packet[10:12] = internet_checksum(packet[:20]).to_bytes(2)
        else:
            # IPv6 only has the total length
            packet[4:6] = (int.from_bytes(packet[4:6]) + length_delta).to_bytes(2)
        return packet

    def strip_ipv4(packet: bytes | bytearray) -> bytes | bytearray | None:
        '''Strips the IPv4 options'''
        ihl = packet[0] & 0xf
        if ihl * 4 > len(packet):
            logger.warning(f'Dropping incomplete IPv4 packet during anonymization: {packet!r}')
            return None

        fragmentation = int.from_bytes(packet[6:8])
        if fragmentation & 0x3fff:
            logger.warning(f'Dropping fragmented IPv4 packet during anonymization: {packet!r}')
            return None

        if packet[9] not in (6, 17):
            # This happens, we don't really care (example: ICMP).
            logger.debug(f'Dropping non-TCP/UDP (protocol {packet[9]}) IPv4 packet during anonymization: {packet!r}')
            return None

        packet = to_bytearray(packet)

        if ihl > 5:
            # Remove IP options
            packet[0]      = 0x45 # Update IHL
            packet[2:4]    = (int.from_bytes(packet[2:4]) - (ihl * 4 - 20)).to_bytes(2) # Update length
            packet[20:ihl] = b'' # Remove options

        # Reset TTL and ToS (DSCP/ECN)
        packet[1] = 0
        packet[8] = min(packet[8], 32)

        packet[10:12]  = b'\0\0' # Clear checksum
        packet[10:12]  = internet_checksum(packet[:20]).to_bytes(2)

        return strip_tcp(packet, 4, 20) if packet[9] == 6 else packet

    def strip_ipv6(packet: bytes | bytearray) -> bytes | bytearray | None:
        '''Strips the IPv6 options'''
        protocol = packet[6]
        next_offset = 40
        while protocol in (0, 43, 44, 50, 51, 60, 135, 139, 140, 253, 254):
            if next_offset + 8 > len(packet):
                logger.warning(f'Dropping incomplete IPv6 packet during anonymization: {packet!r}')
                return None
            protocol = packet[next_offset]
            next_offset = next_offset + 8 + packet[next_offset + 1]

        if protocol not in (6, 17):
            # This happens, we don't really care (example: ICMP).
            logger.debug(f'Dropping non-TCP/UDP (protocol {packet[6]}) IPv6 packet during anonymization: {packet!r}')
            return None

        if next_offset != 40:
            # Remove IPv6 options
            packet = to_bytearray(packet)
            packet[6] = protocol
            packet[40:next_offset] = b''

        if (packet[0] & 0xf) or (packet[1] & 0xf0):
            # Reset traffic class
            packet = to_bytearray(packet)
            packet[0] = packet[0] & 0xf0
            packet[1] = packet[1] & 0x0f

        if packet[7] > 32:
            # Reset hop limit
            packet = to_bytearray(packet)
            packet[7] = 32

        return strip_tcp(packet, 6, 40) if protocol == 6 else packet

    if not packet:
        return None

    match packet[0] >> 4:
        case 4 if len(packet) >= 20:
            return to_bytes(strip_ipv4(packet))
        case 6 if len(packet) >= 40:
            return to_bytes(strip_ipv6(packet))
        case _:
            # Not sure this can actually happen
            logger.debug(f'Dropping non-IP traffic during anonymization: {packet!r}')
            return None


async def ingress_filter(packet: bytes, routes: typing.Sequence[IPNetwork], logger: logging.LoggerAdapter) -> bytes | None:
    '''Filters non-IPv{4,6} and non-TCP/UDP traffic, as well as invalid source addresses.'''
    match (packet + b'\0')[0] >> 4:
        case 4:
            if len(packet) < 20:
                logger.debug(f'Dropping incomplete IPv4 packet in ingress: {packet!r}')
                return None
            if packet[9] not in (6, 17):
                logger.debug(f'Dropping non-TCP/UDP (protocol {packet[9]}) IPv4 packet in ingress: {packet!r}')
                return None
            source = ipaddress.IPv4Address(packet[12:16])
            if not any(source in route for route in routes):
                logger.debug(f'Dropping IPv4 packet with invalid source address {source} ingress: {packet!r}')
                return None
            return packet
        case 6:
            if len(packet) < 40:
                logger.debug(f'Dropping incomplete IPv6 packet in ingress: {packet!r}')
                return None
            if packet[6] not in (6, 17):
                logger.debug(f'Dropping non-TCP/UDP (protocol {packet[6]}) IPv4 packet in ingress: {packet!r}')
                return None
            source = ipaddress.IPv6Address(packet[8:24])
            if not any(source in route for route in routes):
                logger.debug(f'Dropping IPv6 packet with invalid source address {source} ingress: {packet!r}')
                return None
            return packet
        case other_version:
            logger.debug(f'Dropping non-IPv4/IPv6 packet (indicated version is {other_version}) in ingress: {packet!r}')
            return None


async def cancel(awaitable: typing.Awaitable[typing.Any]) -> None:
    '''Cancels a pending Awaitable (coroutine or future)'''
    cancelable = asyncio.ensure_future(awaitable)
    cancelable.cancel()
    try:
        await cancelable
    except asyncio.CancelledError:
        pass # Explicitly ignored, because we explicitly canceled this.


async def safe_gather(*coroutines: typing.Awaitable[typing.Any]) -> list[typing.Any]:
    '''Like asyncio.gather, but cancels all remaining tasks on exception'''
    futures = [asyncio.ensure_future(coro) for coro in coroutines]
    try:
        return await asyncio.gather(*futures)
    except BaseException:
        for future in futures:
            future.cancel()
        await asyncio.gather(*futures, return_exceptions=True)
        raise
