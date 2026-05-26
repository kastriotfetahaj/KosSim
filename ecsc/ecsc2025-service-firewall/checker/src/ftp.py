import asyncio
import dataclasses
import enum
import ipaddress
import logging
import re
import socket
import ssl
import typing

from .types import AsyncConnection, IPAddress
from .utils import accept_one_connection, cancel, null_connection

ActiveFactory: typing.TypeAlias = typing.Callable[[], typing.Awaitable[tuple[IPAddress, int, typing.Awaitable[AsyncConnection]]]]
PassiveFactory: typing.TypeAlias = typing.Callable[[str, int], typing.Awaitable[AsyncConnection]]

class UnexpectedFTPResponse(Exception):
    '''Server responded with an unexpected response'''

class TransferMode(enum.Enum):
    '''Transfer modes for data transfer'''
    PASV = 0
    EPSV = 1
    PORT = 2
    EPRT = 3

    @property
    def is_passive(self) -> bool:
        '''
        Indicates whether this is a passive transfer mode (where the client
        connects to the server on a separate port)
        '''
        return self == TransferMode.PASV or self == TransferMode.EPSV

    @property
    def is_active(self) -> bool:
        '''
        Indicates whether this is an active transfer mode (where the server
        connects back to the client)
        '''
        return self == TransferMode.PORT or self == TransferMode.EPRT


# TypeGuards don't really work well inside the class
def mode_is_passive(mode: TransferMode) -> typing.TypeGuard[typing.Literal[TransferMode.PASV, TransferMode.EPSV]]:
    return mode.is_passive

def mode_is_active(mode: TransferMode) -> typing.TypeGuard[typing.Literal[TransferMode.PORT, TransferMode.EPRT]]:
    return mode.is_active

def make_ssl_context(ca_certificate: str) -> ssl.SSLContext:
    '''Creates an SSL/TLS context'''
    context = ssl.create_default_context()
    context.load_verify_locations(cadata=ca_certificate)
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    return context


@dataclasses.dataclass
class DataChannel:
    '''A data channel'''
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter

    async def write_and_close(self, data: bytes):
        '''Writes data to the data channel, then closes it.'''
        self.writer.write(data)
        await self.writer.drain()
        self.writer.close()
        await self.writer.wait_closed()

    async def upgrade_to_tls(self, ca_certificate: str):
        '''Upgrades the data channel to TLS. This probably only works for passive mode connections?'''
        await self.writer.start_tls(make_ssl_context(ca_certificate))

    async def read_all(self) -> bytes:
        '''Receives data from the data channel until it is closed.'''
        return await self.reader.read()

def no_channel() -> DataChannel:
    '''Returns a dummy channel that does nothing. Needs an active event loop.'''
    return DataChannel(*null_connection())


class Client:
    def __init__(self, *, connection: AsyncConnection, logger: logging.LoggerAdapter):
        '''You should use `FTP` to construct an FTP client.'''
        self.reader, self.writer = connection
        self.logger = logger

    async def _command(self, command: str):
        '''Sends a command to the server'''
        self.writer.write(command.encode() + b'\r\n')
        await self.writer.drain()

    async def _readline(self) -> bytes:
        '''Reads a line from the server'''
        line = await self.reader.readline()
        return line.rstrip(b'\r\n')

    async def _response(self) -> tuple[int, bytes]:
        '''Parses a server response line'''
        line = await self._readline()
        try:
            code, message = line.split(b' ', 1)
            return (int(code), message)
        except ValueError:
            raise UnexpectedFTPResponse(f'Invalid FTP response line: {line!r}')

    async def _response_multiline(self) -> tuple[int, bytes, list[bytes]]:
        '''Parses a multiline response'''
        lines = [await self._readline()]
        while True:
            line = await self._readline()
            if not line.startswith(b' '):
                break
            lines.append(line)
        try:
            code, message = line.split(b' ', 1)
            return (int(code), message, lines)
        except ValueError:
            raise UnexpectedFTPResponse(f'Invalid FTP response line: {line!r}')

    async def _expect(self, expected: int | set[int]) -> bytes:
        '''Receives a server response and checks for the expected response code'''
        code, message = await self._response()
        if isinstance(expected, int):
            expected = { expected }
        if code not in expected:
            raise UnexpectedFTPResponse(f'Received {code}, expected {expected}: {message.decode(errors="replace")}')
        return message

    async def _expect_multiline(self, expected: int | set[int]) -> list[bytes]:
        '''Receives a multiline server response and checks for the expected response code'''
        code, message, lines = await self._response_multiline()
        if isinstance(expected, int):
            expected = { expected }
        if code not in expected:
            raise UnexpectedFTPResponse(f'Received {code}, expected {expected}: {message.decode(errors="replace")}')
        return lines

    def _socket(self) -> socket.socket:
        '''Returns the underlying socket'''
        sock = self.writer.get_extra_info('socket')
        assert sock is not None, 'FTP client is in bad state (no socket in stream writer)'
        return sock

    def local_address(self) -> tuple[IPAddress, int]:
        '''Returns the local address of the socket'''
        host, port, *_ = self._socket().getsockname()
        return ipaddress.ip_address(host), port

    def peer(self) -> tuple[IPAddress, int]:
        '''Returns the peer (remote) address of the socket, i.e. the server address'''
        host, port, *_ = self._socket().getpeername()
        return ipaddress.ip_address(host), port

    # Commands

    async def generic_command(self, command: str, expected: int) -> bytes:
        '''
        Sends a generic command to the server and checks for the expected response code.
        Prefer using the more specialized functions for each command type instead, where
        available.
        '''
        await self._command(command)
        return await self._expect(expected)

    async def user(self, user: str):
        '''USER: Logs in with the given username'''
        await self._command(f'USER {user}')
        await self._expect(331) # "Password required"

    async def pass_(self, password: str):
        '''PASS: Logs in with the given password'''
        await self._command(f'PASS {password}')
        await self._expect(230)

    async def rein(self):
        '''REIN: Reinitializes the connection'''
        await self._command(f'REIN')
        await self._expect(230)

    async def type(self, typ: str):
        '''TYPE: Sets the data encoding mode'''
        await self._command(f'TYPE {typ}')
        await self._expect(200)

    async def port(self, ip: ipaddress.IPv4Address, port: int):
        '''PORT: switches to active mode'''
        spec = str(ip).replace('.', ',') + f',{port >> 8},{port & 0xff}'
        await self._command(f'PORT {spec}')
        await self._expect(200)

    async def eprt(self, ip: IPAddress, port: int):
        '''EPRT: switches to (extended) active mode'''
        family = '1' if ip.version == 4 else '2'
        await self._command(f'EPRT |{family}|{ip}|{port}|'.upper())
        await self._expect(200)

    async def pasv(self) -> tuple[ipaddress.IPv4Address, int]:
        '''PASV: switches to passive mode'''
        await self._command('PASV')
        spec = await self._expect(227)
        m = re.search(br'\(((?:\d+),(?:\d+),(?:\d+),(?:\d+)),(\d+),(\d+)\)', spec)
        if m is None:
            raise UnexpectedFTPResponse(f'PASV returned invalid address {spec.decode(errors="replace")}')
        host = ipaddress.IPv4Address(m.group(1).decode().replace(',', '.'))
        port = int(m.group(2)) << 8 | int(m.group(3))
        return host, port

    async def epsv(self) -> tuple[IPAddress, int]:
        '''EPSV: switches to extended passive mode'''
        await self._command('EPSV')
        spec = await self._expect(229)
        m = re.search(br'\(([!-~][!-~][!-~])(\d+)([!-~])\)', spec)
        if m is None:
            raise UnexpectedFTPResponse(f'EPSV returned invalid response {spec.decode(errors="replace")}')
        delimiter = m.group(3)[0]
        if any(c != delimiter for c in m.group(1)):
            raise UnexpectedFTPResponse(f'EPSV returned invalid response {spec.decode(errors="replace")}')
        port = int(m.group(2))
        host, _ = self.peer()
        return host, port

    async def retr(self, channel: DataChannel, filename: str, *, check_result: bool = True) -> bytes:
        '''RETR: begins retrieving a file over the current data channel'''
        await self._command(f'RETR {filename}')
        await self._expect({125, 150})
        content = await channel.read_all()
        if check_result:
            await self._expect(226)
        else:
            await self._response()
        return content

    async def stor(self, channel: DataChannel, filename: str, content: bytes, *, check_result: bool = True):
        '''STOR: stores a file to the server'''
        await self._command(f'STOR {filename}')
        await self._expect({125, 150})
        await channel.write_and_close(content)
        if check_result:
            await self._expect(226)
        else:
            await self._response()

    async def appe(self, channel: DataChannel, filename: str, content: bytes, *, check_result: bool = True):
        '''APPE: appends to a file on the server'''
        await self._command(f'APPE {filename}')
        await self._expect({125, 150})
        await channel.write_and_close(content)
        if check_result:
            await self._expect(226)
        else:
            await self._response()

    async def stou(self, channel: DataChannel, content: bytes) -> str:
        '''STOU: stores a file to the server at a unique filename'''
        await self._command('STOU')
        response = await self._expect({125, 150})
        m = re.fullmatch(br'FILE: (.*)', response)
        if m is None:
            raise UnexpectedFTPResponse(f'STOU retured invalid response {response.decode(errors="replace")}')
        await channel.write_and_close(content)
        await self._expect(226)
        return m.group(1).decode(errors='replace')

    async def dele(self, filename: str, allow_missing: bool = False):
        '''DELE: deletes a file'''
        await self._command(f'DELE {filename}')
        await self._expect(250 if not allow_missing else {250, 550})

    async def mkd(self, name: str):
        '''MKD: creates a directory'''
        await self._command(f'MKD {name}')
        await self._expect(257)

    async def cwd(self, name: str):
        '''CWD: changes the current working directory'''
        await self._command(f'CWD {name}')
        await self._expect(250)

    async def cdup(self):
        '''CDUP: changes to the parent directory'''
        await self._command('CDUP')
        await self._expect(250)

    async def pwd(self) -> str:
        '''PWD: returns the current working directory'''
        await self._command('PWD')
        response = await self._expect(257)
        if (matched := re.fullmatch(br'"((?:[^"]|"")*)"[^"]*', response)) is not None:
            return matched.group(1).replace(b'""', b'"').decode(errors='replace')
        else:
            raise UnexpectedFTPResponse(f'PWD retured invalid response {response.decode(errors="replace")}')

    async def rmd(self, name: str):
        '''RMD: deletes a directory'''
        await self._command(f'RMD {name}')
        await self._expect(250)

    async def rnfr(self, name: str):
        '''RNFR: Starts a renaming operation'''
        await self._command(f'RNFR {name}')
        await self._expect(350)

    async def rnto(self, name: str):
        '''RNTO: Renames the file indicated in the previous RNFR to the new path'''
        await self._command(f'RNTO {name}')
        await self._expect(250)

    async def rest(self, position: int):
        '''REST: Indicates that the next transfer (RETR or STOR) should start at this file offset'''
        await self._command(f'REST {position}')
        await self._expect(350)

    async def quit(self, *, immediately: bool = False, timeout: float | None = None):
        '''QUIT: terminates the connection'''
        await self._command('QUIT')
        if not immediately:
            try:
                async with asyncio.timeout(timeout):
                    await self._expect(221)
            except asyncio.TimeoutError:
                pass # The server did not respond in time, but also we don't care, we're leaving anyways.
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except asyncio.CancelledError:
            raise
        except BaseException:
            # Typically, something like ssl.SSLError if we kill a TLS connection early
            self.logger.exception('Ignoring unhandled exception during shutdown of FTP connection')

    async def mlsd(self, channel: DataChannel, path: str | None = None) -> dict[str, dict[str, str]]:
        '''MLSD: returns a machine-readable listing of directory entries'''
        await self._command(f'MLSD {path}' if path is not None else 'MLSD')
        await self._expect({125, 150})
        content = await channel.reader.read()
        await self._expect(226)
        entries = {}
        for line in content.split(b'\n'):
            line = line.rstrip(b'\r')
            if not line:
                continue
            try:
                info, name = line.decode(errors='replace').split('; ', 1)
                metadata = {}
                for item in info.split(';'):
                    key, value = item.split('=', 1)
                    metadata[key] = value
                entries[name] = metadata
            except (ValueError, TypeError):
                raise UnexpectedFTPResponse(f'Invalid line in MLSD response: {line.decode(errors="replace")}')
        return entries

    async def mlst(self, path: str) -> dict[str, str]:
        '''MLST: returns a machine-readable listing of metadata for a single path (like MLSD on the parent directory)'''
        await self._command(f'MLST {path}')
        lines = await self._expect_multiline(250)
        if len(lines) != 2:
            raise UnexpectedFTPResponse(f'Unexpected MLST response: {lines!r}')
        if not lines[0].startswith(b'250-Listing'):
            raise UnexpectedFTPResponse(f'Unexpected start of MLST response: {lines[0].decode(errors="replace")}')
        try:
            info, _ = lines[1].decode(errors='replace').split('; ', 1)
            metadata = {}
            for item in info.split(';'):
                key, value = item.split('=', 1)
                metadata[key] = value
            return metadata
        except (ValueError, TypeError):
            raise UnexpectedFTPResponse(f'Invalid line in MLSD response: {lines[1].decode(errors="replace")}')

    async def list_(self, channel: DataChannel, path: str | None = None) -> list[str]:
        '''LIST: returns a human-readable listing of directory entries'''
        await self._command(f'LIST {path}' if path is not None else 'LIST')
        await self._expect({125, 150})
        content = await channel.reader.read()
        await self._expect(226)
        return [line.rstrip(b'\r').decode(errors='replace') for line in content.split(b'\n') if line.strip(b'\r')]

    async def nlst(self, channel: DataChannel, path: str | None = None) -> list[str]:
        '''NLST: returns a compact listing (names only) of directory entries'''
        await self._command(f'NLST {path}' if path is not None else 'NLST')
        await self._expect({125, 150})
        content = await channel.reader.read()
        await self._expect(226)
        return [line.rstrip(b'\r').decode(errors='replace') for line in content.split(b'\n') if line.strip(b'\r')]

    async def size(self, name: str) -> int:
        '''SIZE: returns the size of a file in octets according to the current type.'''
        await self._command(f'SIZE {name}')
        response = await self._expect(213)
        return int(response.strip())

    async def mdtm(self, name: str) -> float:
        '''MDTM: returns the last modification time of a file as a UNIX timestamp.'''
        await self._command(f'MDTM {name}')
        response = await self._expect(213)
        return int(response.strip())

    async def feat(self) -> list[str]:
        '''FEAT: queries available features'''
        await self._command('FEAT')
        lines = await self._expect_multiline(211)
        if lines[0] != b'211-Features supported:':
            raise UnexpectedFTPResponse(f'Unexpected start of FEAT response: {lines[0].decode(errors="replace")}')
        return [feat.strip().decode(errors='replace') for feat in lines]

    async def auth_tls(self, ca_certificate: str):
        '''
        AUTH TLS: enable TLS on the control connection.
        Note that this will break PASV/PORT detection in the firewall.
        '''
        await self._command('AUTH TLS')
        await self._expect(234)
        await self.writer.start_tls(make_ssl_context(ca_certificate))


    # Commands with data transfer

    async def _passive_channel(self, host: IPAddress, port: int,
                                    factory: PassiveFactory | None = None) -> AsyncConnection:
        '''Creates a passive-mode data channel'''
        if factory is None:
            return await asyncio.open_connection(str(host), port)
        else:
            return await factory(str(host), port)

    async def _active_channel(self, factory: ActiveFactory | None = None) -> tuple[IPAddress, int, typing.Awaitable[AsyncConnection]]:
        '''Creates an active-mode data channel'''
        if factory is None:
            host, _ = self.local_address()
            return await accept_one_connection(asyncio.start_server, host=str(host), port=None)
        else:
            return await factory()

    @typing.overload
    async def data_channel(self,
                           mode: typing.Literal[TransferMode.PASV] | typing.Literal[TransferMode.EPSV],
                           factory: PassiveFactory | None = None) -> DataChannel:
        ...

    @typing.overload
    async def data_channel(self,
                           mode: typing.Literal[TransferMode.PORT] | typing.Literal[TransferMode.EPRT],
                           factory: ActiveFactory | None = None) -> DataChannel:
        ...

    async def data_channel(self, mode: TransferMode,
                           factory: ActiveFactory | PassiveFactory | None = None) -> DataChannel:
        '''Switches to the selected transfer mode and establishes the data channel'''
        match mode:
            case TransferMode.PASV:
                host, port = await self.pasv() # This will always give us an IPv4 address
                return DataChannel(*await self._passive_channel(host, port, factory)) # pyright: ignore
            case TransferMode.EPSV:
                host, port = await self.epsv() # This just gives us a port and the peer IP from before
                return DataChannel(*await self._passive_channel(host, port, factory)) # pyright: ignore
            case TransferMode.PORT: # This tells the server to speak IPv4 outbound
                host, port, awaitable = await self._active_channel(factory) # pyright: ignore
                try:
                    assert host.version == 4, 'Got non-IPv4 address for PORT data channel'
                    await self.port(host, port)
                except:
                    await cancel(awaitable)
                    raise
                return DataChannel(*await awaitable)
            case TransferMode.EPRT:
                # Here we can tell the server whatever we want.
                # But for the firewall to allow the connection, the back-connect must be
                #   - from any port on the destination IP of our request
                #   - to the specified address
                # i.e., on the IP address version of the control connection.
                host, port, awaitable = await self._active_channel(factory) # pyright: ignore
                try:
                    local, _ = self.local_address()
                    assert host.version == local.version, 'EPRT IP version mismatch'
                    await self.eprt(host, port)
                except:
                    await cancel(awaitable)
                    raise
                return DataChannel(*await awaitable)


async def FTP(connection: AsyncConnection, logger: logging.LoggerAdapter) -> Client:
    '''Connects to an FTP server'''
    ftp = Client(connection=connection, logger=logger)
    await ftp._expect(220)
    return ftp

