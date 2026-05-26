import asyncio
import errno
import fcntl
import ipaddress
import json
import os
import pathlib
import shlex
import socket
import struct
import subprocess
import typing

from .services import VPN_NETWORKS, SERVICE_NETWORKS
from .types import AsyncConnection, IPAddress, IPNetwork, IPVersion
from .utils import open_udp_connection

PacketHook: typing.TypeAlias = typing.Callable[[bytes], typing.Awaitable[bytes | None]]

class FwmarkCompatible(typing.Protocol):
    def fileno(self) -> int: ...
    def setsockopt(self, level: int, optname: int, value: int, /) -> None: ...

class InterfaceAlreadyExists(Exception):
    '''Failed to create TUN device because the interface already exists.'''

class InternalError(Exception):
    '''The VPN is in an invalid state.'''

class RoutingError(Exception):
    '''The VPN server tried to configure the VPN interface in an incorrect way.'''

class AuthenticationError(Exception):
    '''Failed to authenticate with the VPN server.'''


async def shell_exec(*args, check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    '''Executes a command and waits for it to terminate successfully.'''
    command = [*args]
    process = await asyncio.create_subprocess_exec(*args, **kwargs)
    if subprocess.PIPE in (kwargs.get('stdout'), kwargs.get('stderr')):
        stdout, stderr = await process.communicate(None)
        status = process.returncode
        if status is None:
            raise RuntimeError('Process.communicate returned but did not set return code')
    else:
        status = await process.wait()
        stdout = stderr = None
    if check and status != 0:
        raise InternalError('Command ' + ' '.join(shlex.quote(word) for word in command) + f' failed with exit code {status}')
    return subprocess.CompletedProcess(command, status, stdout, stderr)

TUNSETIFF    = 0x400454ca
IFF_TUN      = 0x0001
IFF_NO_PI    = 0x1000
IFF_TUN_EXCL = 0x8000

VPN_MTU = 1400
VPN_DEFAULT_TABLE = 1337

ADD_ROUTE_ATTEMPTS = 10
ADD_ROUTE_RETRY_DELAY = 0.1

LOCAL_ROUTE_MAX_CHECKS = 100
LOCAL_ROUTE_DELAY = 0.1

class VPN:
    '''A client for the firewall's VPN.'''

    def __init__(self, host: str, port: int, username: str, password: str, interface: str,
                 fwmark: int | None = None, table: int | None = None, mtu: int = VPN_MTU,
                 routes: list[IPNetwork] = VPN_NETWORKS, exclude: list[IPNetwork] = SERVICE_NETWORKS,
                 ip_binary: str | pathlib.Path | None = None, tunctl: str | pathlib.Path | None = None,
                 marker: str | pathlib.Path | None = None, tun_device: str | pathlib.Path | None = None):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.interface = interface
        self.fwmark = fwmark
        self.table = table if table is not None else fwmark
        self.mtu = mtu
        self.routes = routes
        self.exclude = exclude
        self.ip_binary = 'ip' if ip_binary is None else str(ip_binary)
        self.tunctl = tunctl
        self.marker = marker
        self.tun_device = '/dev/net/tun' if tun_device is None else str(tun_device)

        if self.fwmark is not None:
            if self.fwmark <= 0 or self.fwmark >= 32766:
                raise ValueError('Invalid fwmark')
        if self.mtu > 65536:
            raise ValueError('MTU exceeds maximum VPN trasmit size')

        self._ipv4 = None
        self._ipv6 = None
        self._inbound = None
        self._outbound = None
        self._queue = None
        self._reader = None
        self._writer = None
        self._tun = None

        self._rx_hooks: list[PacketHook] = []
        self._tx_hooks: list[PacketHook] = []

    def _partition_routes(self, ip: IPAddress) -> tuple[IPNetwork, list[IPNetwork]]:
        by_type = [route for route in self.routes if route.version == ip.version]
        for_ip = [route for route in by_type if ip in route]
        if not for_ip:
            raise RoutingError(f'{ip} is not assigned to the VPN network')
        target = for_ip.pop()
        if for_ip:
            raise InternalError('Configured overlapping routes')
        others = [route for route in by_type if ip not in route]
        return (target, others)

    async def _configure_route(self, ip: IPAddress, route: IPNetwork):
        if ip.version != route.version:
            raise InternalError(f'IP version mismatch: {ip} paired with {route}')
        # On occasion, even when we add the address with nodad, it will not become valid quite quickly enough.
        # Then, the ip route add will fail very loudly (invalid prefsrc, etc.) and take everything down with it.
        # Therefore, if the first attempt fails, just retry after a short wait.
        last = None
        for _ in range(ADD_ROUTE_ATTEMPTS):
            try:
                if self.fwmark is None:
                    await shell_exec(self.ip_binary, f'-{ip.version}', 'route', 'add', str(route), 'dev', self.interface, 'scope', 'link', 'src', str(ip))
                else:
                    await shell_exec(self.ip_binary, f'-{ip.version}', 'route', 'add', str(route), 'dev', self.interface, 'scope', 'link', 'src', str(ip), 'table', str(self.table))
            except InternalError as e:
                last = e
                await asyncio.sleep(ADD_ROUTE_RETRY_DELAY)
            else:
                return
        raise last or InternalError(f'Failed to add route in {ADD_ROUTE_ATTEMPTS} attempts, but no error was recorded')

    async def _configure_ip(self, ip: IPAddress):
        conflict = next((net for net in self.exclude if net.version == ip.version and ip in net), None)
        if conflict is not None:
            raise RoutingError(f'Assigned IP {ip} is in excluded IP range {conflict}')
        prefix_route, others = self._partition_routes(ip)
        nodad = ['nodad'] if ip.version == 6 else []
        if self.fwmark is None: # Install the prefix route automatically
            await shell_exec(self.ip_binary, f'-{ip.version}', 'addr', 'add', f'{ip}/{prefix_route.prefixlen}', 'dev', self.interface, *nodad)
        else: # Install the prefix route manually, into the target table
            await shell_exec(self.ip_binary, f'-{ip.version}', 'addr', 'add', f'{ip}/{prefix_route.prefixlen}', 'dev', self.interface, 'noprefixroute', *nodad)
            await self._configure_route(ip, prefix_route)
        for route in others:
            await self._configure_route(ip, route)
        # Wait for the IP to show up in the local table.
        # Note that the interface needs to be up for this to happen.
        # We could try to add the local table entry manually, but this does not seem like a good use of our time.
        # Most of the time, we won't be waiting here at all.
        routes = {}
        for _ in range(LOCAL_ROUTE_MAX_CHECKS):
            result = await shell_exec(self.ip_binary, '-j', f'-{ip.version}', 'route', 'show', 'table', 'local', 'dev', self.interface, stdout=subprocess.PIPE)
            routes = json.loads(result.stdout)
            if any(route['type'] == 'local' and route['dst'] == f'{ip}' for route in routes):
                break
            await asyncio.sleep(LOCAL_ROUTE_DELAY)
        else:
            error = InternalError(f'Local routing table entry for {ip} on interface {self.interface} did not show up after {LOCAL_ROUTE_MAX_CHECKS * LOCAL_ROUTE_DELAY:.1f} seconds')
            error.add_note('Last local routing table contained:\n' + repr(routes))
            raise error

    async def _handshake(self):
        if self._reader is None or self._writer is None:
            raise InternalError('No reader or writer for handshake')
        self._writer.write(
            len(self.username.encode()).to_bytes(1) + self.username.encode() +
            len(self.password.encode()).to_bytes(1) + self.password.encode()
        )
        await self._writer.drain()

        try:
            ipv4 = ipaddress.IPv4Address(await self._reader.readexactly(4))
        except asyncio.exceptions.IncompleteReadError:
            # Connection closure on authentication failure will hit here
            raise AuthenticationError('VPN authentication failed')
        if ipv4 != ipaddress.IPv4Address('0.0.0.0'):
            await self._configure_ip(ipv4)
            self._ipv4 = ipv4

        ipv6 = ipaddress.IPv6Address(await self._reader.readexactly(16))
        if ipv6 != ipaddress.IPv6Address('::'):
            await self._configure_ip(ipv6)
            self._ipv6 = ipv6

        if self._ipv4 is None and self._ipv6 is None:
            raise RoutingError('No IP address configured for this user')

    def supported_ip_versions(self) -> list[IPVersion]:
        match (self._ipv4, self._ipv6):
            case (None, None): return []
            case (None, _): return [6]
            case (_, None): return [4]
            case (_, _): return [4, 6]


    @typing.overload
    def ip(self, version: typing.Literal[4]) -> ipaddress.IPv4Address | None:
        ...

    @typing.overload
    def ip(self, version: typing.Literal[6]) -> ipaddress.IPv6Address | None:
        ...

    def ip(self, version: IPVersion) -> IPAddress | None:
        '''Returns the IP address of the VPN client'''
        match version:
            case 4: return self._ipv4
            case 6: return self._ipv6

    async def _inbound_loop(self):
        if self._reader is None or self._tun is None:
            raise InternalError('No reader or TUN device for inbound loop')
        while True:
            header = await self._reader.readexactly(2)
            length = int.from_bytes(header)
            packet = await self._reader.readexactly(length)

            for hook in self._rx_hooks:
                packet = await hook(packet)
                if packet is None:
                    break

            if packet is not None:
                if len(packet) != self._tun.write(packet):
                    raise InternalError('Incomplete write (this should be impossible)')

    async def _outbound_loop(self):
        if self._writer is None or self._queue is None or self._tun is None:
            raise InternalError('No writer, queue, or TUN device for outbound loop')

        while True:
            await self._queue.get() # Cancellable way to ensure the read is nonblocking.
            while True:
                packet = self._tun.read(self.mtu)
                if not packet:
                    break

                for hook in self._tx_hooks:
                    packet = await hook(packet)
                    if packet is None:
                        break

                if packet is not None:
                    header = len(packet).to_bytes(2)
                    self._writer.write(header)
                    self._writer.write(packet)
                    await self._writer.drain()

    def _outbound_callback(self):
        # Signal the outbound loop.
        if self._queue is None:
            raise InternalError('No queue for outbound callback')
        self._queue.put_nowait(None)

    def is_running(self) -> bool:
        return any(thing is not None for thing in [
            self._inbound, self._outbound, self._reader, self._writer
        ])

    async def create(self):
        '''Creates the VPN interface. This is an idempotent operation.'''
        if self._tun is not None:
            return
        self._tun = open(self.tun_device, 'r+b', buffering=0)
        try:
            flags = fcntl.fcntl(self._tun.fileno(), fcntl.F_GETFL)
            fcntl.fcntl(self._tun.fileno(), fcntl.F_SETFL, flags | os.O_NONBLOCK)

            tun_flags = IFF_TUN | IFF_TUN_EXCL | IFF_NO_PI
            if self.tunctl is not None:
                tun_fd = self._tun.fileno()
                flags = fcntl.fcntl(tun_fd, fcntl.F_GETFD)
                fcntl.fcntl(tun_fd, fcntl.F_SETFD, flags & ~fcntl.FD_CLOEXEC)
                result = await shell_exec(str(self.tunctl), str(tun_fd), str(tun_flags), self.interface,
                                          check=False, close_fds=False)
                status = result.returncode
                fcntl.fcntl(tun_fd, fcntl.F_SETFD, flags)
                if status == errno.EBUSY:
                    raise InterfaceAlreadyExists()
                elif status != 0:
                    code = errno.errorcode.get(status, f'unknown errno {status}')
                    raise InternalError(f'{self.tunctl} failed to configure TUN interface ({code})')
            else:
                ifreq = struct.pack('16sH22s', self.interface.encode('ascii'), tun_flags, b'')
                try:
                    fcntl.ioctl(self._tun, TUNSETIFF, ifreq)
                except OSError as error:
                    if error.errno == errno.EBUSY: # Separate this case out.
                        raise InterfaceAlreadyExists()
                    raise

            await shell_exec(self.ip_binary, 'link', 'set', 'dev', self.interface, 'mtu', str(self.mtu))
            await shell_exec(self.ip_binary, 'link', 'set', 'dev', self.interface, 'up')

            # TODO: For good measure, check that both net.ipv4.conf.{all,interface}.forwarding are 0
            # TODO: For good measure, check that both net.ipv6.conf.{all,interface}.forwarding are 0
            # TODO: _Ensure_ that one of net.ipv4.conf.{all,interface}.src_valid_mark is 1
        except:
            self._tun.close()
            self._tun = None
            raise

    async def start(self):
        '''Starts the VPN.'''
        if self.is_running():
            raise InternalError('VPN is already running')

        await self.create()
        if self._tun is None:
            raise InternalError('Failed to create TUN device (somehow, without erroring)')
        try:
            self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
            await self._handshake()

            if self.fwmark is not None:
                await shell_exec(self.ip_binary, '-4', 'rule', 'add', 'from', 'all', 'fwmark', str(self.fwmark), 'lookup', str(self.table))
                await shell_exec(self.ip_binary, '-6', 'rule', 'add', 'from', 'all', 'fwmark', str(self.fwmark), 'lookup', str(self.table))

            self._queue = asyncio.Queue()
            self._inbound = asyncio.create_task(self._inbound_loop())
            self._outbound = asyncio.create_task(self._outbound_loop())
            asyncio.get_running_loop().add_reader(self._tun, self._outbound_callback)
        except:
            await self.stop()
            raise

    async def stop(self):
        '''Stops the VPN. You should run this inside `asyncio.shield` to avoid cancellation.'''
        async_exception = None
        if self._outbound is not None:
            self._outbound.cancel()
            # get exceptions from async task
            try:
                await self._outbound
            except asyncio.CancelledError:
                pass
            except BaseException as e:
                async_exception = e
            self._outbound = None
        if self._inbound is not None:
            self._inbound.cancel()
            # get exceptions from async task
            try:
                await self._inbound
            except asyncio.CancelledError:
                pass
            except BaseException as e:
                async_exception = e
            self._inbound = None
        if self._writer is not None:
            self._writer.close()
            await self._writer.wait_closed()
            self._writer = None
        self._reader = None
        self._queue = None
        if self._tun is not None:
            asyncio.get_running_loop().remove_reader(self._tun)
            await shell_exec(self.ip_binary, 'link', 'set', 'dev', self.interface, 'down', check=False)
            await shell_exec(self.ip_binary, '-4', 'addr', 'flush', 'dev', self.interface, check=False)
            await shell_exec(self.ip_binary, '-6', 'addr', 'flush', 'dev', self.interface, check=False)
        if self.fwmark is not None:
            await shell_exec(self.ip_binary, '-4', 'rule', 'del', 'from', 'all', 'fwmark', str(self.fwmark), 'lookup', str(self.table), check=False)
            await shell_exec(self.ip_binary, '-6', 'rule', 'del', 'from', 'all', 'fwmark', str(self.fwmark), 'lookup', str(self.table), check=False)
        if self.table is not None:
            if self._ipv4 is not None:
                await shell_exec(self.ip_binary, '-4', 'route', 'flush', 'table', str(self.table), check=False)
            if self._ipv6 is not None:
                await shell_exec(self.ip_binary, '-6', 'route', 'flush', 'table', str(self.table), check=False)
        if self._tun is not None:
            # Only close the TUN device (and thus remove the interface) once all the table infrastructure has been cleaned up
            self._tun.close()
            self._tun = None

        if async_exception:
            raise async_exception

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exception_type, exception, _traceback):
        if exception_type is not None and exception is not None:
            if self.is_running():
                typing.cast(BaseException, exception).add_note(f'Shutting down VPN {self.interface} (IPs {self._ipv4} / {self._ipv6})')
        await asyncio.shield(asyncio.create_task(self.stop()))

    async def set_fwmark(self, sock: FwmarkCompatible):
        if self.fwmark is not None:
            if self.marker is None:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_MARK, self.fwmark)
            else:
                fd = sock.fileno()
                flags = fcntl.fcntl(fd, fcntl.F_GETFD)
                fcntl.fcntl(fd, fcntl.F_SETFD, flags & ~fcntl.FD_CLOEXEC)
                result = await shell_exec(str(self.marker), str(fd), str(self.fwmark),
                                          check=False, close_fds=False)
                status = result.returncode
                fcntl.fcntl(fd, fcntl.F_SETFD, flags)
                if status != 0:
                    code = errno.errorcode.get(status, f'unknown errno {status}')
                    raise InternalError(f'{self.marker} failed to set fwmark on socket ({code})')

    async def create_socket(self, family: int = 0, type: int = socket.SOCK_STREAM, proto: int = 0):
        '''Creates a socket that passes traffic through the VPN'''
        sock = socket.socket(family, type, proto)
        sock.setblocking(False)
        await self.set_fwmark(sock)
        return sock

    def _derive_address_family(self, host: str | IPAddress | None) -> socket.AddressFamily:
        '''Tries to derive the address family from a host specification. We can only do IP addresses here.'''
        if isinstance(host, ipaddress.IPv4Address):
            return socket.AF_INET
        elif isinstance(host, ipaddress.IPv6Address):
            return socket.AF_INET6
        else:
            try:
                ipaddress.IPv4Address(host)
                return socket.AF_INET
            except ipaddress.AddressValueError:
                pass

            try:
                ipaddress.IPv6Address(host)
                return socket.AF_INET6
            except ipaddress.AddressValueError:
                pass

            return socket.AF_INET6 if 6 in self.supported_ip_versions() else socket.AF_INET

    async def open_connection(self, host: str | IPAddress | None = None, port: int | None = None, *,
                              socket_hook: typing.Callable[[socket.socket], socket.socket] | None = None,
                              socket_type: int | socket.SocketKind | None = None,
                              bind_to_interface: bool = True,
                              ipv6_dual_stack: bool = True,
                              **kwargs) -> AsyncConnection:
        '''Limited equivalent of asyncio.open_connection (but with UDP support) for the VPN'''
        original_host, host = host, str(host)

        sock = kwargs.pop('sock', None)
        if sock is not None:
            await self.set_fwmark(sock)
            if socket_type not in (sock.type, None):
                raise ValueError('Cannot override socket type in open_connection')
        else:
            # This doesn't do all the dance that asyncio.open_connection does.
            # If you need proper address resolution, call loop.getaddrinfo first.
            # If you need to bind the socket to a local address, use the socket_hook.
            if (family := kwargs.get('family', None)) is None:
                family = self._derive_address_family(original_host)
            sock = await self.create_socket(family, socket_type if socket_type is not None else socket.SOCK_STREAM, kwargs.get('proto', 0))

        try:
            if socket_hook is not None:
                sock = socket_hook(sock)

            if bind_to_interface:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, self.interface.encode())
            if not ipv6_dual_stack and sock.family == socket.AF_INET6:
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, True)

            if host is not None or port is not None:
                try:
                    await asyncio.get_running_loop().sock_connect(sock, (host, port))
                except asyncio.CancelledError as e:
                    e.add_note(f'Connection cancelled while connecting to {host}:{port}\n(We are {self._ipv4} / {self._ipv6})')
                    raise e

            match sock.type:
                case socket.SOCK_STREAM: return await asyncio.open_connection(host=None, port=None, sock=sock, **kwargs)
                case socket.SOCK_DGRAM: return await open_udp_connection(sock)
                case _: raise ValueError('Unknown socket type')
        except BaseException:
            sock.close()
            raise

    async def start_server(self, callback: typing.Callable[[asyncio.StreamReader, asyncio.StreamWriter], typing.Awaitable[None] | None],
                           host: str | IPAddress | None = None, port: int | None = None, *,
                           socket_hook: typing.Callable[[socket.socket], socket.socket] | None = None,
                           bind_to_interface: bool = True,
                           ipv6_dual_stack: bool = True,
                           reuse_address: bool = True,
                           **kwargs) -> asyncio.Server:
        '''Limited equivalent of asyncio.start_server (with SO_BINDTODEVICE support) for the VPN'''
        sock = kwargs.pop('sock', None)
        if sock is not None:
            await self.set_fwmark(sock)
        else:
            # This doesn't do all the dance that asyncio.open_connection does.
            # If you need proper address resolution, call loop.getaddrinfo first.
            # If you need to bind the socket to a local address, use the socket_hook.
            if (family := kwargs.get('family', None)) is None:
                family = self._derive_address_family(host)
            sock = await self.create_socket(family, socket.SOCK_STREAM, kwargs.get('proto', 0))

        try:
            if socket_hook is not None:
                sock = socket_hook(sock)

            if bind_to_interface:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, self.interface.encode())
            if not ipv6_dual_stack and sock.family == socket.AF_INET6:
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, True)
            if reuse_address:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)

            if host is None:
                match sock.family:
                    case socket.AF_INET: host = '0.0.0.0'
                    case socket.AF_INET6: host = '::'
                    case _: raise ValueError(f'No default host for address family {sock.family}')
            else:
                host = str(host)

            sock.bind((host, port or 0))
        except BaseException:
            sock.close()
            raise

        # SO_MARK and SO_BINDTODEVICE are inherited (inet_csk_clone_lock in "new" kernels)
        return await asyncio.start_server(callback, host=None, port=None, sock=sock, **kwargs)

    async def send_raw_packet(self, packet: bytes, drain: bool = True):
        '''Sends a raw packet over the network'''
        if self._writer is None:
            raise InternalError('No writer for send_raw_packet')
        header = len(packet).to_bytes(2)
        self._writer.write(header + packet)
        if drain:
            await self._writer.drain()

    def add_rx_packet_hook(self, hook: PacketHook):
        '''Adds a hook that is invoked for every inbound packet'''
        self._rx_hooks.append(hook)

    def remove_rx_packet_hook(self, hook: PacketHook):
        '''Removes a hook added with `add_rx_packet_hook`'''
        self._rx_hooks.remove(hook)

    def add_tx_packet_hook(self, hook: PacketHook):
        '''Adds a hook that is invoked for every outbound packet'''
        self._tx_hooks.append(hook)

    def remove_tx_packet_hook(self, hook: PacketHook):
        '''Removes a hook added with `add_tx_packet_hook`'''
        self._tx_hooks.remove(hook)


if __name__ == '__main__':
    # You probably don't want to run this from the checker, but this is a good way to check if it works.
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
            fwmark = args.fwmark,
            table = args.table,
            mtu = args.mtu,
            routes = args.route if args.route else VPN_NETWORKS,
            exclude = args.exclude if args.exclude else [] if args.route else SERVICE_NETWORKS,
            ip_binary = args.ip,
            tunctl = args.tunctl,
            marker = args.marker,
            tun_device = args.tun,
        )
        async with vpn:
            try:
                await asyncio.Future() # This will never resolve until the task is cancelled
            except asyncio.CancelledError:
                raise

    parser = argparse.ArgumentParser()
    parser.add_argument('-u', '--username', help='VPN username', type=str)
    parser.add_argument('-p', '--password', help='VPN password', type=str)
    parser.add_argument('-P', '--port', help='VPN port', type=int, default=9100)
    parser.add_argument('-i', '--interface', help='Interface name for the TUN device', type=str)
    parser.add_argument('-m', '--mtu', help='MTU for the TUN device', type=int, default=VPN_MTU)
    parser.add_argument('-f', '--fwmark', help='Route only traffic for this firewall mark', type=int)
    parser.add_argument('-t', '--table', help='Use this routing table for fwmark matching', type=int)
    parser.add_argument('-r', '--route', help='Route these IP ranges through the VPN', action='append', type=ipaddress.ip_network)
    parser.add_argument('-x', '--exclude', help='Prohibit assigning this IP range to the interface', action='append', type=ipaddress.ip_network)
    parser.add_argument('--tunctl', help='Use this tunctl binary to configure the interface', type=pathlib.Path)
    parser.add_argument('--marker', help='Use this fwmark binary to configure sockets', type=pathlib.Path)
    parser.add_argument('--ip', help='Use this ip (iproute2) binary to configure the interface', type=pathlib.Path)
    parser.add_argument('--tun', help='Use this path for the TUN device (usually /dev/net/tun)', type=pathlib.Path)
    parser.add_argument('host', help='VPN host', type=str)
    args = parser.parse_args()

    if args.fwmark is None and args.table is not None:
        parser.error('--table requires --fwmark')

    args.username = input('VPN username: ') if args.username is None else args.username
    args.password = getpass.getpass('VPN password: ') if args.password is None else args.password
    args.interface = (f'vpn-{args.fwmark}' if args.fwmark is not None else 'vpn') if not args.interface else args.interface

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    task = asyncio.ensure_future(main(args), loop=loop)
    for signal in [signal.SIGINT, signal.SIGTERM]:
        loop.add_signal_handler(signal, task.cancel)
    try:
        loop.run_until_complete(task)
    except asyncio.CancelledError:
        pass
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
