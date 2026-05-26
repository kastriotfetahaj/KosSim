#!/usr/bin/env python3
import asyncio
import errno
import fcntl
import ipaddress
import os
import pathlib
import socket
import struct
import subprocess
import typing
import warnings


TUNSETIFF    = 0x400454ca
IFF_TUN      = 0x0001
IFF_NO_PI    = 0x1000
IFF_TUN_EXCL = 0x8000


ALLOWED_IPV4 = ipaddress.IPv4Network('10.0.0.0/8')
ALLOWED_IPV6 = ipaddress.IPv6Network('fd00:ec5c::/80')

SERVICE_IPV4 = ipaddress.IPv4Network('10.0.0.0/24')
SERVICE_IPV6 = ipaddress.IPv6Network('fd00:ec5c::/112')


@typing.overload
def exclude(network: ipaddress.IPv4Network,
            exclude: typing.Iterable[ipaddress.IPv4Network | ipaddress.IPv6Network]) \
        -> typing.Sequence[ipaddress.IPv4Network]:
    ...

@typing.overload
def exclude(network: ipaddress.IPv6Network,
            exclude: typing.Iterable[ipaddress.IPv4Network | ipaddress.IPv6Network]) \
        -> typing.Sequence[ipaddress.IPv6Network]:
    ...

def exclude(network: ipaddress.IPv4Network | ipaddress.IPv6Network,
            exclude: typing.Iterable[ipaddress.IPv4Network | ipaddress.IPv6Network]) \
        -> typing.Sequence[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    '''Excludes multiple network ranges from a base network.'''
    networks = [network]
    for exclusion in exclude:
        after = []
        for current in networks:
            if isinstance(current, ipaddress.IPv4Network) and isinstance(exclusion, ipaddress.IPv4Network):
                replacement = current.address_exclude(exclusion)
            elif isinstance(current, ipaddress.IPv6Network) and isinstance(exclusion, ipaddress.IPv6Network):
                replacement = current.address_exclude(exclusion)
            else:
                replacement = [current]
            after.extend(replacement)
        networks = after
    return networks


async def run_command(*args, check: bool = True, **kwargs) -> int:
    '''Executes a command and waits for it to terminate'''
    command = [str(arg) for arg in args]
    process = await asyncio.create_subprocess_exec(*command, **kwargs)
    status = await process.wait()
    if check and status != 0:
        raise subprocess.CalledProcessError(status, command)
    return status


def ensure_file(path: pathlib.Path, content: str):
    '''Ensures a file (typically in procfs) has the specified content'''
    if path.read_text().strip() != content:
        path.write_text(content)


class VPN:
    '''Client for the VPN'''
    def __init__(self, host: str, port: int, username: str, password: str,
                 interface: str, mark: int, mtu: int, tun_device: pathlib.Path,
                 inbound: bool, nftable: str,
                 exclude: list[ipaddress.IPv4Network | ipaddress.IPv6Network],
                 proto_filter: bool, strip_packets: bool):
        self.host = host
        self.port = port
        self.username = username.encode()
        self.password = password.encode()
        self.interface = interface
        self.mark = mark
        self.mtu = mtu
        self.tun_device = tun_device
        self.inbound = inbound
        self.nftable = nftable
        self.exclude = exclude
        self.should_drop = VPN._proto_filter if proto_filter else lambda _: False
        self.strip_packet = self._strip_packet if strip_packets else lambda data: data

        if not 1280 <= mtu <= 1480:
            raise ValueError('Invalid MTU')
        if not 256 <= mark <= 32764:
            raise ValueError('Invalid rule table index')

        self._tun = None
        self._reader = None
        self._writer = None
        self._ipv4 = None
        self._ipv6 = None
        self._inbound = None
        self._outbound = None
        self._queue = None
        self._shutdown = False

    @staticmethod
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

    @staticmethod
    def update_internet_checksum(checksum: int, *,
                                 remove: typing.Iterable[bytearray | bytes | memoryview] | None = None,
                                 add: typing.Iterable[bytearray | bytes | memoryview] | None = None) -> int:
        '''Updates an IP/TCP/UDP checksum with added/removed data.'''
        checksum ^= 0xffff
        if remove is not None:
            for item in remove:
                checksum += VPN.internet_checksum(item)
        if add is not None:
            for item in add:
                checksum += VPN.internet_checksum(item) ^ 0xffff
        while checksum > 0xffff:
            checksum = (checksum & 0xffff) + (checksum >> 16)
        return checksum ^ 0xffff

    @staticmethod
    def _proto_filter(packet: bytes) -> bool:
        '''Returns True (drop) if this is non-IPv{4,6} or non-TCP/UDP traffic.'''
        match (packet + b'\0')[0] >> 4:
            case 4: return len(packet) < 20 or packet[9] not in (6, 17)
            case 6: return len(packet) < 40 or packet[6] not in (6, 17)
            case _: return True

    def _strip_packet(self, packet: bytes) -> bytes:
        '''Strips TCP and IP options from a packet.'''
        match (packet + b'\0')[0] >> 4:
            case 4 if len(packet) >= 20: return bytes(self._strip_ipv4(packet))
            case 6 if len(packet) >= 40: return bytes(self._strip_ipv6(packet))
            case _: return packet

    @staticmethod
    def _recompute_ipv4_checksum(packet: bytearray) -> None:
        '''Updates the IPv4 checksum.'''
        packet[10:12]  = b'\0\0' # Clear checksum
        packet[10:12]  = VPN.internet_checksum(packet[:20]).to_bytes(2)

    def _strip_ipv4(self, packet: bytes | bytearray) -> bytes | bytearray:
        '''Strips IPv4 options from a packet.'''
        ihl = packet[0] & 0xf
        if ihl * 4 > len(packet):
            warnings.warn('Dropping packet with incomplete IPv4 header (cannot strip)')
            return b''
        fragmentation = int.from_bytes(packet[6:8])
        if fragmentation & 0x3fff:
            warnings.warn('Dropping fragmented IPv4 packet (cannot strip)')
            return b'' # Just drop this.
        if ihl > 5 or packet[1] or packet[8] > 32:
            packet = bytearray(packet)
            packet[0] = 0x45 # Update IHL
            packet[1] = 0 # Clear ToS
            packet[2:4] = (int.from_bytes(packet[2:4]) - (ihl * 4 - 20)).to_bytes(2) # Update length
            packet[8] = min(packet[8], 32) # Clamp TTL
            packet[20:ihl] = b'' # Remove options
            VPN._recompute_ipv4_checksum(packet)
        return self._strip_tcp(packet, 4) if packet[9] == 6 else packet

    def _strip_ipv6(self, packet: bytes | bytearray) -> bytes | bytearray:
        '''Strips IPv6 options from a packet.'''
        protocol = packet[6]
        next_offset = 40
        while protocol in (0, 43, 44, 50, 51, 60, 135, 139, 140, 253, 254):
            if next_offset + 8 > len(packet):
                warnings.warn('Dropping packet with incomplete IPv6 extension header (cannot strip)')
                return b''
            protocol = packet[next_offset]
            next_offset = next_offset + 8 + packet[next_offset + 1]
        if next_offset != 40 or packet[0] & 0xf or packet[1] & 0xf0 or packet[7] > 32:
            packet = bytearray(packet)
            packet[0] &= 0xf0 # Clear traffic class
            packet[1] &= 0x0f # (dto.)
            packet[6] = protocol # Replace next header type
            packet[7] = min(packet[7], 32) # Clamp hop limit
            packet[40:next_offset] = b'' # Remove options
        return self._strip_tcp(packet, 6) if protocol == 6 else packet

    def _strip_tcp(self, packet: bytes | bytearray, ip_version: typing.Literal[4, 6]) -> bytes | bytearray:
        '''Strips TCP options from a packet.'''
        tcp_offset = 20 if ip_version == 4 else 40
        if tcp_offset + 20 > len(packet):
            warnings.warn('Dropping packet with incomplete TCP header (cannot strip)')
            return b''

        payload_offset = tcp_offset + (packet[tcp_offset + 12] >> 4) * 4
        if payload_offset <= tcp_offset + 20:
            return packet
        if payload_offset > len(packet):
            warnings.warn('Dropping incomplete TCP packet (cannot strip)')
            return b''

        options_length = payload_offset - (tcp_offset + 20)
        tcp_length = len(packet) - tcp_offset

        # Actually set the correct MSS according to the MTU; strip the rest.
        tcp_syn = bool(packet[tcp_offset + 13] & 2)
        replacement = (b'\x02\x04' + (self.mtu - tcp_offset - 20).to_bytes(2)) if tcp_syn else b''
        new_offset = ((packet[tcp_offset + 12] & 0xf) | (((20 + len(replacement)) // 4) << 4))

        length_delta = len(replacement) - options_length

        checksum = VPN.update_internet_checksum(
            int.from_bytes(packet[tcp_offset + 16:tcp_offset + 18]),
            remove = [
                packet[tcp_offset + 12:tcp_offset + 14], # Old offset
                packet[tcp_offset + 20:payload_offset], # Options
                tcp_length.to_bytes(2), # Old length
            ],
            add = [
                # New offset
                new_offset.to_bytes(1) + packet[tcp_offset + 13].to_bytes(1),
                replacement,
                (tcp_length + length_delta).to_bytes(2), # New length
            ],
        )

        packet = bytearray(packet)
        packet[tcp_offset + 12] = new_offset
        packet[tcp_offset + 16:tcp_offset + 18] = checksum.to_bytes(2)
        packet[tcp_offset + 20:payload_offset] = replacement

        # Update total length and possibly the IPv4 header checksum
        if ip_version == 4:
            packet[2:4] = (int.from_bytes(packet[2:4]) + length_delta).to_bytes(2)
            VPN._recompute_ipv4_checksum(packet)
        else:
            packet[4:6] = (int.from_bytes(packet[4:6]) + length_delta).to_bytes(2)

        return packet

    async def _inbound_loop(self):
        '''Forwards inbound traffic'''
        if self._reader is None or self._tun is None:
            raise RuntimeError('Inbound loop has no reader or no TUN device')
        while True:
            header = await self._reader.readexactly(2)
            length = int.from_bytes(header)
            packet = await self._reader.readexactly(length)
            if self.should_drop(packet):
                continue
            self._tun.write(packet)

    async def _outbound_loop(self):
        '''Forwards outbound traffic'''
        if self._writer is None or self._queue is None or self._tun is None:
            raise RuntimeError('Outbound loop has no writer, no queue, or no TUN device')
        while True:
            await self._queue.get()
            while True:
                packet = self._tun.read(self.mtu)
                if not packet:
                    break
                packet = self.strip_packet(packet)
                if not packet or self.should_drop(packet):
                    continue
                header = len(packet).to_bytes(2)
                self._writer.write(header)
                self._writer.write(packet)
                await self._writer.drain()

    def _outbound_callback(self):
        '''Signals the outbound loop that the TUN device is ready for reading'''
        if self._shutdown:
            return # No need to signal if we're shutting down anyways.
        if self._queue is None:
            raise RuntimeError('Outbound callback has no queue')
        self._queue.put_nowait(None)

    def _rule(self):
        '''`ip rule` for routing traffic through the VPN'''
        return ['not', 'from', 'all', 'fwmark', self.mark, 'table', self.mark]

    async def connect(self):
        '''Connects to the VPN'''
        if self._shutdown:
            self._shutdown = False

        # Open the TUN device.
        if self._tun is not None:
            return
        self._tun = open(self.tun_device, 'r+b', buffering=0)
        try:
            flags = fcntl.fcntl(self._tun.fileno(), fcntl.F_GETFL)
            fcntl.fcntl(self._tun.fileno(), fcntl.F_SETFL, flags | os.O_NONBLOCK)

            ifreq = struct.pack('16sH22s', self.interface.encode('ascii'), IFF_TUN | IFF_TUN_EXCL | IFF_NO_PI, b'')
            try:
                fcntl.ioctl(self._tun, TUNSETIFF, ifreq)
            except OSError as error:
                if error.errno == errno.EBUSY:
                    raise RuntimeError(f'Interface {self.interface} already exists')
                raise

            await run_command('ip', 'link', 'set', 'dev', self.interface, 'mtu', self.mtu)
            await run_command('ip', 'link', 'set', 'dev', self.interface, 'up')
            if not self.inbound:
                await run_command('nft', 'add', 'table', 'inet', self.nftable)
                await run_command('nft', 'add', 'chain', 'inet', self.nftable, 'prerouting',
                                  '{ type filter hook prerouting priority filter; policy accept; }')
                await run_command('nft', 'add', 'rule', 'inet', self.nftable, 'prerouting',
                                  f'iif {self.interface} ip saddr != {SERVICE_IPV4} drop')
                await run_command('nft', 'add', 'rule', 'inet', self.nftable, 'prerouting',
                                  f'iif {self.interface} ip6 saddr != {SERVICE_IPV6} drop')
            ensure_file(pathlib.Path('/proc/sys/net/ipv4/conf/') / self.interface / 'forwarding', '0')
            ensure_file(pathlib.Path('/proc/sys/net/ipv4/conf/') / self.interface / 'src_valid_mark', '1')
            ensure_file(pathlib.Path('/proc/sys/net/ipv6/conf/') / self.interface / 'forwarding', '0')
            ensure_file(pathlib.Path('/proc/sys/net/ipv6/conf/') / self.interface / 'accept_ra', '0')
            ensure_file(pathlib.Path('/proc/sys/net/ipv6/conf/') / self.interface / 'accept_redirects', '0')

            self._reader, self._writer = await asyncio.open_connection(self.host, self.port)

            so = self._writer.get_extra_info('socket')
            if so is None:
                raise RuntimeError('Failed to get socket')
            elif not hasattr(so, 'setsockopt'):
                # This should be an asyncio.trsock.TransportSocket, which we don't have access to.
                # But anything with setsockopt will do.
                raise RuntimeError(f'Failed to get socket (got unexpected object {so!r} instead)')

            self._writer.write(
                len(self.username).to_bytes(1) + self.username +
                len(self.password).to_bytes(1) + self.password
            )
            await self._writer.drain()

            so.setsockopt(socket.SOL_SOCKET, socket.SO_MARK, self.mark)

            try:
                ipv4 = ipaddress.IPv4Address(await self._reader.readexactly(4))
            except asyncio.exceptions.IncompleteReadError:
                raise RuntimeError('Authentication failed')


            if not ipv4.is_unspecified:
                if ipv4 not in ALLOWED_IPV4 or ipv4 == ALLOWED_IPV4.broadcast_address or ipv4 in SERVICE_IPV4:
                    raise RuntimeError(f'VPN assigned disallowed address {ipv4}')
                self._ipv4 = ipv4
                await run_command('ip', 'addr',
                                    'add', f'{ipv4}/32',
                                    'dev', self.interface)
                for network in exclude(ALLOWED_IPV4, self.exclude):
                    await run_command('ip', '-4', 'route',
                                        'add', network,
                                        'dev', self.interface,
                                        'scope', 'link',
                                        'table', self.mark)
                await run_command('ip', '-4', 'rule', 'add', *self._rule())

            ipv6 = ipaddress.IPv6Address(await self._reader.readexactly(16))
            if not ipv6.is_unspecified:
                if ipv6 not in ALLOWED_IPV6 or ipv6 == ALLOWED_IPV6.broadcast_address or ipv6 in SERVICE_IPV6:
                    raise RuntimeError(f'VPN assigned disallowed address {ipv6}')
                self._ipv6 = ipv6
                await run_command('ip', 'addr',
                                    'add', f'{ipv6}/128',
                                    'dev', self.interface)
                for network in exclude(ALLOWED_IPV6, self.exclude):
                    await run_command('ip', '-6', 'route',
                                        'add', network,
                                        'dev', self.interface,
                                        'scope', 'link',
                                        'table', self.mark)
                await run_command('ip', '-6', 'rule', 'add', *self._rule())

            if self._ipv4 is None and self._ipv6 is None:
                raise RuntimeError('VPN assigned no IP addresses')

            self._queue = asyncio.Queue()
            self._inbound = asyncio.create_task(self._inbound_loop())
            self._outbound = asyncio.create_task(self._outbound_loop())
            asyncio.get_running_loop().add_reader(self._tun, self._outbound_callback)
        except:
            await self.disconnect()
            raise

    async def _teardown(self):
        '''Does the actual teardown'''
        self._shutdown = True
        if self._outbound is not None:
            self._outbound.cancel()
            self._outbound = None
        if self._inbound is not None:
            self._inbound.cancel()
            self._inbound = None
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except BrokenPipeError:
                pass # Server went away, I guess.
            self._writer = None
        self._reader = None
        self._queue = None
        if self._tun is not None:
            await run_command('ip', 'link', 'set', 'dev', self.interface, 'down', check=False)
        if not self.inbound:
            await run_command('nft', 'flush', 'table', 'inet', self.nftable, check=False)
            await run_command('nft', 'delete', 'table', 'inet', self.nftable, check=False)
        if self._ipv6 is not None:
            await run_command('ip', '-6', 'rule', 'del', *self._rule(), check=False)
            await run_command('ip', '-6', 'route', 'flush', 'table', self.mark, check=False)
            self._ipv6 = None
        if self._ipv4 is not None:
            await run_command('ip', '-4', 'rule', 'del', *self._rule(), check=False)
            await run_command('ip', '-4', 'route', 'flush', 'table', self.mark, check=False)
            self._ipv4 = None
        if self._tun is not None:
            asyncio.get_running_loop().remove_reader(self._tun)
            self._tun.close()
            self._tun = None
        self._shutdown = False

    def ips(self):
        '''Returns a list of IPs assigned to the VPN'''
        return [ip for ip in (self._ipv4, self._ipv6) if ip is not None]

    async def disconnect(self):
        '''Disconnects the VPN client from the VPN'''
        # Teardown runs even if the client task is cancelled.
        await asyncio.shield(asyncio.create_task(self._teardown()))

    async def __aenter__(self):
        '''On entry to an `async with` block, start the client'''
        await self.connect()
        return self

    async def __aexit__(self, *_):
        '''On exit from an `async with` block, disconnect the client'''
        await self.disconnect()


if __name__ == '__main__':
    import argparse
    import getpass
    import signal

    async def main(args):
        vpn = VPN(
            host = args.host,
            port = args.port,
            username = args.username,
            password = args.password,
            interface = args.interface,
            mark = args.mark,
            mtu = args.mtu,
            tun_device = args.tun,
            inbound = args.inbound,
            nftable = args.nftable,
            exclude = args.exclude,
            proto_filter = not args.all_protocols,
            strip_packets = args.strip,
        )
        try:
            async with vpn:
                print('\x1b[2mconnected successfully\x1b[0m')
                ips = ' and '.join(f'\x1b[22;32m{ip}\x1b[2;39m' for ip in vpn.ips())
                print(f'\x1b[2massigned {ips} to interface \x1b[22;32m{vpn.interface}\x1b[0m')
                await asyncio.Future() # This will never resolve until the task is cancelled
        except RuntimeError as error:
            print('\x1b[1K\r\x1b[1;31m' + error.args[0] + '\x1b[0m')
        except asyncio.CancelledError:
            print('\x1b[1K\r\x1b[2mshutting down\x1b[0m')
            raise

    parser = argparse.ArgumentParser()
    parser.add_argument('-u', '--username', help='VPN username', type=str)
    parser.add_argument('-p', '--password', help='VPN password', type=str)
    parser.add_argument('-P', '--port', help='VPN port (default: 9100)', type=int, default=9100)
    parser.add_argument('-i', '--interface', help='Interface name for the TUN device', type=str)
    parser.add_argument('-m', '--mtu', help='MTU for the TUN device (default: 1400)', type=int, default=1400)
    parser.add_argument('-M', '--mark', help='Use this rule table and fwmark (default: 9100)', type=int, default=9100)
    parser.add_argument('-T', '--tun', help='Use this path for the TUN device (default: /dev/net/tun)', type=pathlib.Path)
    parser.add_argument('-x', '--exclude', help='Do not route these IP ranges through the VPN', action='append', default=[], type=ipaddress.ip_network)
    parser.add_argument('-N', '--nftable', help='Name for the netfilter table (default: interface name)')
    parser.add_argument('-I', '--inbound', help='Allow inbound traffic from non-service hosts (default: no)', action=argparse.BooleanOptionalAction)
    parser.add_argument('--all-protocols', help='Allow non-TCP/UDP-over-IPv{4,6} traffic (default: no)', action=argparse.BooleanOptionalAction)
    parser.add_argument('--strip', help='Strip outbound packets to reduce fingerprintability (default: yes)', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('host', help='VPN host', type=str)
    args = parser.parse_args()

    args.username = input('\x1b[2menter username:\x1b[0m ') if args.username is None else args.username
    args.password = getpass.getpass('\x1b[2menter password:\x1b[0m ') if args.password is None else args.password
    args.interface = 'ecsc0' if not args.interface else args.interface
    args.tun = pathlib.Path('/dev/net/tun') if not args.tun else args.tun
    args.nftable = args.interface if not args.nftable else args.nftable

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    task = asyncio.ensure_future(main(args), loop=loop)
    for signal in [signal.SIGINT, signal.SIGTERM]:
        loop.add_signal_handler(signal, task.cancel)
    try:
        loop.run_until_complete(task)
    except asyncio.CancelledError:
        pass # We want this to happen.
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
