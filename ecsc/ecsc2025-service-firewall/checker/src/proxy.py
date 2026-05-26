import asyncio
import functools
import ipaddress
import socket
import typing
import warnings

from .types import AsyncConnection, IPAddress
from .utils import internet_checksum, safe_gather
from .vpn import VPN


Address: typing.TypeAlias = tuple[IPAddress | str, int]
MakeConnection: typing.TypeAlias = typing.Callable[[IPAddress | str, int], typing.Awaitable[AsyncConnection]]


class ProxyError(Exception):
    '''The proxy is in an invalid state.'''


class BaseProxy:
    '''
    A TCP proxy that proxies connections through the VPN that could otherwise not use the VPN.

    We need this e.g. for library code that opens its own sockets on which we cannot set SO_MARK.
    '''

    def __init__(self, connect: MakeConnection, bind: Address, target: Address):
        '''Creates a new proxy. This does not start the proxy server yet.'''
        self.connect = connect
        self.bind = bind
        self.target = target
        self._server = None

    @property
    def port(self) -> int | None:
        '''The port to which this server is bound.'''
        return self._server.sockets[0].getsockname()[1] if self._server is not None else None

    async def start(self):
        '''Starts the proxy. If the proxy is already running, this does nothing.'''
        if self._server is not None:
            return
        self._server = await asyncio.start_server(self._handle_client, str(self.bind[0]), self.bind[1])

    async def stop(self):
        '''Stops the proxy.'''
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed() # This may be broken (see docs), but it doesn't _really_ matter.
            self._server = None

    async def __aenter__(self) -> typing.Self:
        '''Starts the proxy (for use in `async with`).'''
        await self.start()
        return self

    async def __aexit__(self, *_):
        '''Stops the proxy when leaving `async with`.'''
        await self.stop()

    async def _handle_client(self, downstream_reader: asyncio.StreamReader, downstream_writer: asyncio.StreamWriter):
        '''Handles a single TCP client.'''
        try:
            upstream_reader, upstream_writer = await self.connect(*self.target)
        except BaseException:
            # If the upstream connection fails, clean up here instead.
            downstream_writer.close()
            await downstream_writer.wait_closed()
            raise
        up   = asyncio.create_task(Proxy._forward(downstream_reader, upstream_writer))
        down = asyncio.create_task(Proxy._forward(upstream_reader, downstream_writer))
        await safe_gather(up, down)

    @staticmethod
    async def _forward(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        '''Forwards traffic (unidirectionally) from a StreamReader to a StreamWriter.'''
        try:
            while not reader.at_eof():
                data = await reader.read(4096)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()


class Proxy(BaseProxy):
    '''
    A TCP proxy that proxies connections through the VPN that could otherwise not use the VPN.

    This implementation uses the default `vpn.open_connection` (and thus the kernel network
    stack / routing setup) to create new connections.
    '''

    def __init__(self, vpn: VPN, bind: Address, target: Address):
        '''Creates a new proxy. This does not start the proxy server yet.'''
        super().__init__(vpn.open_connection, bind, target)


class UnidirectionalRewriter:
    '''
    A TCP/UDP traffic rewriter using the hooks in the VPN.

    Note that this _cannot_ handle IP fragmentation (since the reordering means you _have_ to
    do reassembly, which _sucks_ and also needs collecting _all traffic_ etc etc.).

    I expect "normal" users to just use nftables to do the rewriting, or use scapy to send L4
    directly. This is just here so we can do this without messing with nftables.
    '''

    def __init__(self, vpn: VPN, direction: typing.Literal['tx', 'rx'],
                 match_local: tuple[IPAddress | str | None, int | None] | None,
                 match_remote: tuple[IPAddress | str | None, int | None] | None,
                 set_local: tuple[IPAddress | str | None, int | None] | None,
                 set_remote: tuple[IPAddress | str | None, int | None] | None,
                 protocols: set[int] | None = None):
        self._vpn = vpn
        self._direction = direction

        laddr, self._lport = match_local or (None, None)
        raddr, self._rport = match_remote or (None, None)
        new_laddr, self._new_lport = set_local or (None, None)
        new_raddr, self._new_rport = set_remote or (None, None)
        self._laddr = ipaddress.ip_address(laddr) if laddr is not None else None
        self._raddr = ipaddress.ip_address(raddr) if raddr is not None else None
        self._new_laddr = ipaddress.ip_address(new_laddr) if new_laddr is not None else None
        self._new_raddr = ipaddress.ip_address(new_raddr) if new_raddr is not None else None
        if len(set(ip.version for ip in (self._laddr, self._raddr, self._new_laddr, self._new_raddr) if ip)) != 1:
            raise ValueError('Cannot rewrite traffic across IP version')
        self._protos = protocols

    def _hook(self, packet: bytes, tx: bool) -> bytes:
        if not packet: return packet
        ip_version = packet[0] >> 4
        match ip_version:
            case 4: return self._hook_ipv4(packet, tx)
            case 6: return self._hook_ipv6(packet, tx)
            case _: return packet

    def _hook_ipv4(self, packet: bytes, tx: bool) -> bytes:
        try:
            if len(packet) < 20:
                return packet

            packet_saddr = ipaddress.IPv4Address(packet[12:16])
            packet_daddr = ipaddress.IPv4Address(packet[16:20])

            packet_laddr = packet_saddr if tx else packet_daddr
            packet_raddr = packet_daddr if tx else packet_saddr

            if self._laddr is not None and packet_laddr != self._laddr:
                return packet # Not from us
            if self._raddr is not None and packet_raddr != self._raddr:
                return packet # Not to the target

            proto = packet[9]
            if self._protos is not None and proto not in self._protos:
                return packet # Not our protocol type

            # Check for fragmentation
            offset = int.from_bytes(packet[6:8], 'big') & 0x1fff
            more_fragments = bool(packet[6] & 0x20)
            if offset or more_fragments:
                warnings.warn(f'Encountered fragmented IPv4 traffic from {packet_saddr} to {packet_daddr}, and it might be a rewriting candidate')
                return packet # ... Fragmented, we don't know how to handle this - just forward it, it might not be ours.

            l4_offset = (packet[0] & 0xf) * 4

            laddr = (self._new_laddr if self._new_laddr is not None else packet_laddr).packed
            raddr = (self._new_raddr if self._new_raddr is not None else packet_raddr).packed

            saddr = laddr if tx else raddr
            daddr = raddr if tx else laddr

            l3 = bytearray(packet[:10] + b'\0\0' + saddr + daddr + packet[20:l4_offset])
            l3[10:12] = internet_checksum(l3).to_bytes(2, 'big')
            l3 = bytes(l3)

            l4 = packet[l4_offset:]

            l3_pseudoheader = saddr + daddr + proto.to_bytes(2, 'big') + len(l4).to_bytes(2, 'big')

            return self._hook_l4(packet, proto, l3, l4, l3_pseudoheader, tx)
        except IndexError:
            return packet # Missing fields somewhere

    def _hook_ipv6(self, packet: bytes, tx: bool) -> bytes:
        try:
            if len(packet) < 40:
                return packet

            packet_saddr = ipaddress.IPv6Address(packet[8:24])
            packet_daddr = ipaddress.IPv6Address(packet[24:40])

            packet_laddr = packet_saddr if tx else packet_daddr
            packet_raddr = packet_daddr if tx else packet_saddr

            if self._laddr is not None and packet_laddr != self._laddr:
                return packet # Not from us
            if self._raddr is not None and packet_raddr != self._raddr:
                return packet # Not to the target

            proto = packet[6]
            l4_offset = 40
            while True:
                match proto:
                    case socket.IPPROTO_HOPOPTS | socket.IPPROTO_ROUTING | socket.IPPROTO_DSTOPTS | 135: # 135: IPPROTO_MH
                        proto = packet[l4_offset]
                        l4_offset += 1 + packet[l4_offset + 1]
                    case socket.IPPROTO_FRAGMENT:
                        if len(packet) < l4_offset + 8:
                            return packet
                        offset = int.from_bytes(packet[l4_offset + 2:l4_offset + 4], 'big') >> 3
                        more_fragments = bool(packet[l4_offset + 4] & 1)
                        if offset or more_fragments:
                            warnings.warn(f'Encountered fragmented IPv6 traffic from {packet_saddr} to {packet_daddr}, and it might be a rewriting candidate')
                            return packet
                        proto = packet[l4_offset]
                        l4_offset += 8
                    case _: # Not an extension header that we expect. Could be the final protocol.
                        break

            if self._protos is not None and proto not in self._protos:
                return packet # Not our protocol type

            laddr = (self._new_laddr if self._new_laddr is not None else packet_laddr).packed
            raddr = (self._new_raddr if self._new_raddr is not None else packet_raddr).packed

            saddr = laddr if tx else raddr
            daddr = raddr if tx else laddr

            l3 = packet[:8] + saddr + daddr + packet[40:l4_offset]
            l4 = packet[l4_offset:]
            l3_pseudoheader = saddr + daddr + len(l4).to_bytes(4, 'big') + proto.to_bytes(4, 'big')

            return self._hook_l4(packet, proto, l3, l4, l3_pseudoheader, tx)
        except IndexError:
            return packet # Missing fields somewhere

    def _hook_l4(self, original: bytes, proto: int, l3: bytes, l4: bytes, l3_pseudoheader: bytes, tx: bool) -> bytes:
        if len(l4) < 4:
            return original

        packet_sport = int.from_bytes(l4[0:2], 'big')
        packet_dport = int.from_bytes(l4[2:4], 'big')

        packet_lport = packet_sport if tx else packet_dport
        packet_rport = packet_dport if tx else packet_sport

        if self._lport is not None and packet_lport != self._lport:
            return original # Not from our port
        if self._rport is not None and packet_rport != self._rport:
            return original # Not to the target port

        lport = (self._new_lport if self._new_lport is not None else packet_lport).to_bytes(2, 'big')
        rport = (self._new_rport if self._new_rport is not None else packet_rport).to_bytes(2, 'big')

        sport = lport if tx else rport
        dport = rport if tx else lport

        l4 = sport + dport + l4[4:]
        checksum_offset = None
        match proto:
            case socket.IPPROTO_TCP: checksum_offset = 16
            case socket.IPPROTO_UDP: checksum_offset = 6
        if checksum_offset is not None:
            before, after = l4[:checksum_offset], l4[checksum_offset + 2:]
            checksum = internet_checksum(l3_pseudoheader + before + after)
            l4 = before + checksum.to_bytes(2, 'big') + after

        return l3 + l4

    async def _hook_tx(self, packet: bytes) -> bytes:
        return self._hook(packet, tx=True)

    async def _hook_rx(self, packet: bytes) -> bytes:
        return self._hook(packet, tx=False)

    def start(self):
        match self._direction:
            case 'tx': self._vpn.add_tx_packet_hook(self._hook_tx)
            case 'rx': self._vpn.add_rx_packet_hook(self._hook_rx)

    def stop(self):
        match self._direction:
            case 'tx': self._vpn.remove_tx_packet_hook(self._hook_tx)
            case 'rx': self._vpn.remove_rx_packet_hook(self._hook_rx)

    # Support for `with UnidirectionalRewriter(...)`
    def __enter__(self) -> typing.Self:
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()


class Rewriter:
    '''
    A TCP/UDP traffic rewriter using the hooks in the VPN.

    Note that this _cannot_ handle IP fragmentation (since the reordering means you _have_ to
    do reassembly, which _sucks_ and also needs collecting _all traffic_ etc etc.).

    I expect "normal" users to just use nftables to do the rewriting, or use scapy to send L4
    directly. This is just here so we can do this without messing with nftables.
    '''

    def __init__(self, vpn: VPN,
                 original_local: tuple[IPAddress | str | None, int | None],
                 original_remote: tuple[IPAddress | str | None, int | None],
                 set_local: tuple[IPAddress | str | None, int | None] | None,
                 set_remote: tuple[IPAddress | str | None, int | None] | None,
                 protocols: set[int] | None = None):

        self._tx = UnidirectionalRewriter(vpn, 'tx', original_local, original_remote, set_local, set_remote, protocols)

        match_laddr = set_local[0] if set_local is not None and set_local[0] is not None else original_local[0]
        match_lport = set_local[1] if set_local is not None and set_local[1] is not None else original_local[1]
        match_raddr = set_remote[0] if set_remote is not None and set_remote[0] is not None else original_remote[0]
        match_rport = set_remote[1] if set_remote is not None and set_remote[1] is not None else original_remote[1]

        self._rx = UnidirectionalRewriter(vpn, 'rx', (match_laddr, match_lport), (match_raddr, match_rport), original_local, original_remote, protocols)

    def start(self):
        self._tx.start()
        self._rx.start()

    def stop(self):
        self._tx.stop()
        self._rx.stop()

    # Support for `with Rewriter(...)`
    def __enter__(self) -> typing.Self:
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()


class RewritingProxy(BaseProxy):
    '''
    A TCP proxy that proxies connections through the VPN that could otherwise not use the VPN.

    This implementation additionally hooks the VPN to rewrite traffic sent from/to this proxy.
    '''
    # NB: Traffic does not get fragmented at an IP level before the first four bytes of the L4
    # header. Only data can be fragmented, and the offset steps in multiples of 8. Since
    # duplicate fragments are not OK, it is guaranteed that we always have the L4 ports in
    # the first IP fragment.

    def __init__(self, vpn: VPN, bind: Address, target: Address,
                 set_local: tuple[IPAddress | str | None, int | None] | None = None,
                 set_remote: tuple[IPAddress | str | None, int | None] | None = None):
        '''Creates a new proxy. This does not start the proxy server yet.'''
        self._vpn = vpn
        self._target = (ipaddress.ip_address(target[0]), target[1])

        self._local = set_local
        self._remote = set_remote

        self._connections = 0

        super().__init__(self._open_connection, bind, target)

    async def _open_connection(self, host: IPAddress | str, port: int) -> AsyncConnection:
        if self._connections and self._local is not None and self._local[1] is not None:
            raise ProxyError('Trying to set same local port in multiple connections')
        self._connections += 1

        try:
            rewriter = None
            def on_socket_created(so: socket.socket) -> socket.socket:
                nonlocal rewriter

                # Commit the socket to an outbound port.
                ip = self._vpn.ip(6 if so.family == socket.AF_INET6 else 4)
                if ip is None:
                    raise ProxyError('VPN has no IP address for socket family')
                match ip.version:
                    case 4: address = (str(ip), 0)
                    case 6: address = (str(ip), 0, 0, 0)
                so.bind(address)
                port = so.getsockname()[1]

                # Install the VPN hooks.
                rewriter = Rewriter(self._vpn,
                    (ip, port),
                    self._target,
                    self._local,
                    self._remote,
                    { socket.IPPROTO_TCP },
                )
                rewriter.start()
                return so


            reader, writer = await self._vpn.open_connection(host, port, socket_hook=on_socket_created)
            if rewriter is None:
                raise ProxyError('No rewriter after opening connection through the RewritingProxy')

            if reader.at_eof() or writer.is_closing():
                self._connections -= 1
                rewriter.stop()
            else:
                protocol = writer.transport.get_protocol()
                original_connection_lost = protocol.connection_lost
                @functools.wraps(protocol.connection_lost)
                def connection_lost(*args, _rewriter = rewriter, **kwargs):
                    result = original_connection_lost(*args, **kwargs)
                    self._connections -= 1
                    _rewriter.stop()
                    return result
                protocol.connection_lost = connection_lost
            return (reader, writer)
        except:
            self._connections -= 1
            raise



