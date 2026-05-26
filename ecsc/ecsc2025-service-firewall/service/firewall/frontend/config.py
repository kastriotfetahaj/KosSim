import ipaddress
import pathlib
import msgspec
import typing

class ConfigBase(msgspec.Struct, forbid_unknown_fields=True, rename='kebab'):
    '''Base type to configure msgspec'''

class ManagerConfig(ConfigBase):
    '''SNMP manager config'''
    path: str
    '''Path where the manager API is served'''

    auth_community: str
    '''
    Community used for the set request
    Use "__COMMUNITY__" as a placeholder for a community passed in via the
    SNMP_AUTH_COMMUNITY or SNMP_AUTH_COMMUNITY_FILE environment variables.
    '''
    default_community: str
    '''Community used for all other requests'''

class Config(ConfigBase):
    '''Frontend and firewall config'''
    database: str
    '''
    Database connection string ("postgresql://...").
    Use "__PASSWORD__" as a placeholder for a password passed in via the DB_PASSWORD
    or DB_PASSWORD_FILE environment variables.
    '''

    ipv4: tuple[ipaddress.IPv4Address, ipaddress.IPv4Address]
    '''IPv4 address range that may be assigned to users.'''

    ipv6: tuple[ipaddress.IPv6Address, ipaddress.IPv6Address]
    '''IPv6 address range that may be assigned to users.'''

    account_lifetime: int
    '''Account lifetime, in seconds. Should not be below the "actual" account lifetime.'''

    manager: ManagerConfig
    '''SNMP manager configuration.'''


def load_config(path: pathlib.Path) -> Config:
    def custom_decode(type: typing.Type, obj: typing.Any) -> typing.Any:
        if type is ipaddress.IPv4Address:
            assert isinstance(obj, str), 'IPv4 address is not a string'
            return ipaddress.IPv4Address(obj)
        elif type is ipaddress.IPv6Address:
            assert isinstance(obj, str), 'IPv6 address is not a string'
            return ipaddress.IPv6Address(obj)
        elif type is pathlib.Path:
            assert isinstance(obj, str), 'Path is not a string'
            return pathlib.Path(obj)
        else:
            raise NotImplementedError(f'No custom decoder for {type}')

    return msgspec.toml.decode(path.read_bytes(), type=Config, dec_hook=custom_decode)
