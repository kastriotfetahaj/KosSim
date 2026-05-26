import asyncio
import ipaddress
import typing

AsyncConnection: typing.TypeAlias = tuple[asyncio.StreamReader, asyncio.StreamWriter]

IPAddress: typing.TypeAlias = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork: typing.TypeAlias = ipaddress.IPv4Network | ipaddress.IPv6Network
IPVersion: typing.TypeAlias = typing.Literal[4, 6]
