import enum
import ipaddress
import typing

from .types import IPAddress, IPVersion

VPN_NETWORKS = [
    ipaddress.ip_network('10.0.0.0/8'),
    ipaddress.ip_network('fd00:ec5c::/80'),
]
'''IP ranges in the VPN network.'''

SERVICE_NETWORKS = [
    ipaddress.ip_network('10.0.0.0/24'),
    ipaddress.ip_network('fd00:ec5c::/112'),
]
'''IP ranges within the VPN network reserved for services.'''

assert all(
    any(vpn_net.supernet_of(service_net) for vpn_net in VPN_NETWORKS # pyright: ignore [reportArgumentType] (the if below handles this case)
        if vpn_net.version == service_net.version)
    for service_net in SERVICE_NETWORKS
), 'Service network is not reachable through configured VPN network'

assert all(
    sum(1 for net in SERVICE_NETWORKS if net.version == ip_version) == 1
    for ip_version in (4, 6)
), 'Multiple service network ranges for a single address family'


class Service(enum.Enum):
    '''The different services behind the firewall/VPN.'''
    Firewall = 1
    FTP      = 2
    DB       = 3
    SNMP     = 4

    @typing.overload
    def ip(self, version: typing.Literal[4]) -> ipaddress.IPv4Address:
        ...

    @typing.overload
    def ip(self, version: typing.Literal[6]) -> ipaddress.IPv6Address:
        ...

    def ip(self, version: IPVersion) -> IPAddress:
        '''Returns an IP address for the specified family, or None'''
        net = next(net for net in SERVICE_NETWORKS if net.version == version)
        return net.network_address + int(self.value)

    @property
    def ipv4(self) -> ipaddress.IPv4Address:
        '''Returns the IPv4 address of the service.'''
        return self.ip(4)

    @property
    def ipv6(self) -> ipaddress.IPv6Address:
        '''Returns the IPv6 address of the service.'''
        return self.ip(6)

    @property
    def ips(self) -> list[IPAddress]:
        '''Returns the IP addresses of this service.'''
        return [net.network_address + int(self.value) for net in SERVICE_NETWORKS]

    @property
    def port(self) -> int:
        '''Returns the primary service port for this service.'''
        return {
            Service.Firewall: 9100,
            Service.FTP:      21,
            Service.DB:       5432,
            Service.SNMP:     1161,
        }[self]
