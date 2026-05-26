import ipaddress
import typing

from enochecker3.types import MumbleException
from logging import LoggerAdapter

from .frontend import FrontendClient
from .services import Service
from .types import IPAddress

CheckFunction: typing.TypeAlias = typing.Callable[[FrontendClient, LoggerAdapter], typing.Awaitable[None]]

monitoring_labels = (
    "dbSocketIPv4",
    "dbSocketIPv6High",
    "dbSocketIPv6Low",
    "dbSocketPort",
    "snmpSocketIPv4",
    "snmpSocketIPv6High",
    "snmpSocketIPv6Low",
    "dbIPv4",
    "dbIPv6High",
    "dbIPv6Low",
    "snmpIPv4",
    "snmpIPv6High",
    "snmpIPv6Low",
    "dbNameHash",
    "dbUserHash",
    "dbSystemUserHash",
    "dbActiveUsers",
    "statsFreeIPRanges",
)


def int_to_ipv4(i: int) -> ipaddress.IPv4Address:
    try:
        return ipaddress.IPv4Address(i.to_bytes(4, byteorder="little"))
    except OverflowError:
        raise MumbleException('SNMP monitoring reported incorrect status')


def ints_to_ipv6(i1: int, i2: int) -> ipaddress.IPv6Address:
    try:
        return ipaddress.IPv6Address(i1.to_bytes(8, byteorder="little") + i2.to_bytes(8, byteorder="little"))
    except OverflowError:
        raise MumbleException('SNMP monitoring reported incorrect status')


async def get_value(frontend_client: FrontendClient, name: str) -> int:
    value = await frontend_client.snmp_get_monitoring(name)
    if not isinstance(value, int):
        raise MumbleException('SNMP monitoring reported incorrect status')
    return value


def check_ipv4(name: str, location: str, expected: IPAddress) -> CheckFunction:
    async def monitoring_ipv4_checker(frontend_client: FrontendClient, logger: LoggerAdapter):
        address = int_to_ipv4(await get_value(frontend_client, name))
        if address != expected and not address.is_unspecified:
            # Unspecified IPs are fine because the value might be 0 if no connection uses this IP version
            logger.info(f"{location} has unexpected IP address {address} (not {expected} or unspecified)")
            raise MumbleException('SNMP monitoring reported incorrect status')

    return monitoring_ipv4_checker


def check_ipv6(name_high: str, name_low: str, location: str, expected: IPAddress) -> CheckFunction:
    async def monitoring_ipv6_checker(frontend_client: FrontendClient, logger: LoggerAdapter):
        high = await get_value(frontend_client, name_high)
        low = await get_value(frontend_client, name_low)
        address = ints_to_ipv6(high, low)
        if address != expected and not address.is_unspecified:
            # Unspecified IPs are fine because the value might be 0 if no connection uses this IP version
            # There is the rare chance that the value is 0 while reading the high part
            # and then gets updated before reading the low part, which will result in
            # an unexpected IP address. Thus, accept the case that only the high part
            # is zero.
            if high == 0:
                expected_low = int.from_bytes(expected.packed[8:], "little")
                if low == expected_low:
                    return
                logger.info(f"{location} has unexpected IP address {address} (high part was 0, low part was {low} but expected {expected_low})")
                raise MumbleException('SNMP monitoring reported incorrect status')
            elif low == 0:
                expected_high = int.from_bytes(expected.packed[:8], "little")
                if high == expected_high:
                    return
                logger.info(f"{location} has unexpected IP address {address} (low part was 0, high part was {high} but expected {expected_high})")
                raise MumbleException('SNMP monitoring reported incorrect status')
            else:
                logger.info(f"{location} has unexpected IP address {address} (not {expected} or unspecified)")
                raise MumbleException('SNMP monitoring reported incorrect status')

    return monitoring_ipv6_checker


def check_constant(name: str, location: str, expected: int) -> CheckFunction:
    async def monitoring_constant_checker(frontend_client: FrontendClient, logger: LoggerAdapter):
        value = await get_value(frontend_client, name)
        if value == 0:
            # This is kinda stupid, but values can be zero if they have never been requested.
            # Fully reliable checks are done via user monitoring
            return
        if value != expected:
            logger.info(f"{location} has unexpected value {value} (not {expected} or zero)")
            raise MumbleException('SNMP monitoring reported incorrect status')

    return monitoring_constant_checker


def check_nop(name: str) -> CheckFunction:
    async def monitoring_nop_checker(frontend_client: FrontendClient, _: LoggerAdapter):
        await get_value(frontend_client, name)

    return monitoring_nop_checker


check_functions: tuple[CheckFunction, ...] = (
    check_ipv4("dbSocketIPv4", "Database", Service.DB.ip(4)),
    check_ipv6("dbSocketIPv6High", "dbSocketIPv6Low", "Database", Service.DB.ip(6)),
    check_constant("dbSocketPort", "Database Port", Service.DB.port),
    check_ipv4("snmpSocketIPv4", "Agent", Service.Firewall.ip(4)),
    check_ipv6("snmpSocketIPv6High", "snmpSocketIPv6Low", "Agent", Service.Firewall.ip(6)),
    check_ipv4("dbIPv4", "Database", Service.DB.ip(4)),
    check_ipv6("dbIPv6High", "dbIPv6Low", "Database", Service.DB.ip(6)),
    check_ipv4("snmpIPv4", "Agent", Service.Firewall.ip(4)),
    check_ipv6("snmpIPv6High", "snmpSocketIPv6Low", "Agent", Service.Firewall.ip(6)),
    check_constant("dbNameHash", "Database Name", 694727318),
    check_constant("dbUserHash", "Database User", 694727318),
    check_constant("dbSystemUserHash", "Database System User", 9223372036854775808),
    # We have no reference values for these checkes
    check_nop("dbActiveUsers"),
    check_nop("statsFreeIPRanges"),
)


async def get_value_user(frontend_client: FrontendClient, name: str) -> None | int | str:
    return await frontend_client.snmp_get_user_monitoring(name)


def check_ip_user(name: str, location: str, expected: list[IPAddress]) -> CheckFunction:
    async def monitoring_ip_checker(frontend_client: FrontendClient, logger: LoggerAdapter):
        value = await get_value_user(frontend_client, name)
        if not isinstance(value, str):
            logger.info(f"{value!r} (obtained as IP address for {location}) is not a string")
            raise MumbleException('SNMP monitoring reported incorrect status')
        try:
            address = ipaddress.ip_address(bytes.fromhex(value))
        except (TypeError, ValueError):
            logger.info(f"IP address {value!r} for {location} is invalid")
            raise MumbleException('SNMP monitoring reported incorrect status')
        if address not in expected:
            logger.info(f"{location} has unexpected IP address {address} (not in {expected})")
            raise MumbleException('SNMP monitoring reported incorrect status')

    return monitoring_ip_checker


def check_constant_user(name: str, location: str, expected: None | int | str) -> CheckFunction:
    async def monitoring_constant_checker(frontend_client: FrontendClient, logger: LoggerAdapter):
        value = await get_value_user(frontend_client, name)
        if value != expected:
            logger.info(f"{location} has unexpected value {value!r} (not {expected!r})")
            raise MumbleException('SNMP monitoring reported incorrect status')

    return monitoring_constant_checker


def check_nop_user(name: str) -> CheckFunction:
    async def monitoring_nop_checker(frontend_client: FrontendClient, _: LoggerAdapter):
        await get_value_user(frontend_client, name)

    return monitoring_nop_checker


check_functions_user: tuple[CheckFunction, ...] = (
    check_ip_user("querySocketServerAddr", "Database", Service.DB.ips),
    check_ip_user("querySocketClientAddr", "Agent", Service.Firewall.ips),
    check_ip_user("queryDbServerAddr", "Database", Service.DB.ips),
    check_ip_user("queryDbClientAddr", "Agent", Service.Firewall.ips),
    check_constant_user("queryDbNameHash", "Database Name", 694727318),
    check_constant_user("queryDbSessionUserHash", "Database User", 694727318),
    check_constant_user("queryDbSystemUserHash", "Database System User", None),
    check_nop_user("queryDbActiveUsers"),
    check_nop_user("queryDbFreeIPRanges"),
    check_constant_user("queryDbUserDroppedPackets", "Dropped Packets", 0),
    check_constant_user("queryDbUserDroppedBytes", "Dropped Bytes", 0),
)
