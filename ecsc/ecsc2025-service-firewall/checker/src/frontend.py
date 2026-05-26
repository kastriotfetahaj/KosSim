from httpx import AsyncClient, Response
from logging import LoggerAdapter

from enochecker3.types import MumbleException

import binascii
import re
import typing

class FrontendClient:
    '''A client for the firewall's web frontend.'''
    def __init__(self, client: AsyncClient, logger: LoggerAdapter, username: str, password: str, timeout: int = 10):
        self.client = client
        self.logger = logger
        self.username = username
        self.password = password
        self.client.timeout = timeout

    async def register(self):
        '''Registers the user in the frontend. The frontend will automatically log in the new user.'''
        response = await self.client.post('/register', data={'username': self.username, 'password': self.password})
        if response.status_code != 302:
            self.logger.error(f'Frontend user registration for {self.username} had unexpected status {response.status_code} (expected 302)')
            self.logger.debug(f'Response contents:\n{response.text}')
            raise MumbleException('Failed to register user')

    async def login(self):
        '''Logs into the frontend.'''
        response = await self.client.post('/login', data={'username': self.username, 'password': self.password})
        if response.status_code != 302:
            self.logger.error(f'Frontend login for {self.username} had unexpected status {response.status_code} (expected 302)')
            self.logger.debug(f'Response contents:\n{response.text}')
            raise MumbleException('Failed to log in user')

    async def logout(self):
        '''Logs out of the frontend.'''
        response = await self.client.post('/logout')
        if response.status_code != 302:
            self.logger.error(f'Frontend logout for {self.username} had unexpected status {response.status_code} (expected 302)')
            self.logger.debug(f'Response contents:\n{response.text}')
            raise MumbleException('Failed to log out user')

    async def overview(self) -> Response:
        '''Fetches the overview page (at /).'''
        response = await self.client.get('/')
        if response.status_code != 200:
            self.logger.error(f'Frontend request (GET /) had unexpected status {response.status_code} (expected 200)')
            self.logger.debug(f'Response contents:\n{response.text}')
            raise MumbleException('Invalid response from frontend')
        return response

    async def traffic(self) -> Response:
        '''Fetches the dropped traffic page (at /traffic/).'''
        response = await self.client.get('/traffic/')
        if response.status_code != 200:
            self.logger.error(f'Frontend request (GET /traffic/) had unexpected status {response.status_code} (expected 200)')
            self.logger.debug(f'Response contents:\n{response.text}')
            raise MumbleException('Invalid response from frontend')
        return response

    async def dropped_packets(self) -> typing.AsyncGenerator[bytes, None]:
        '''Fetches the list of dropped packets and parses them out of the HTML.'''
        response = await self.traffic()
        for match in re.finditer(r'<td class="packet">((?:[0-9a-f]{2})*)</td>', response.text):
            yield bytes.fromhex(match.group(1))

    async def ca_certificate(self) -> str:
        '''Fetches the CA certificate (at /static/ca.crt).'''
        response = await self.client.get('/static/ca.crt')
        if response.status_code != 200:
            self.logger.error(f'Frontend request (GET /static/ca.crt) had unexpected status {response.status_code} (expected 200)')
            self.logger.debug(f'Response contents:\n{response.text}')
            raise MumbleException('Failed to retrieve CA certificate')
        return response.text # NB: This is str because way down the line, _ssl.c will only treat str as PEM

    async def snmp_do_request(
        self,
        method: str,
        path: str,
        return_keys: typing.Iterable[str],
        return_types: typing.Iterable[type | None],
        **kwargs
        ) -> list[typing.Any]:

        response = await getattr(self.client, method)(path, **kwargs)
        if response.status_code != 200:
            self.logger.error(f'Manager {path} {method}: unexpected status {response.status_code} (expected 200)')
            self.logger.debug(f'Response contents:\n{response.text}')
            raise MumbleException('Invalid response from frontend')

        try:
            json = response.json()
        except:
            self.logger.error(f'Manager {path} {method}: response contained invalid json')
            self.logger.debug(f'Response contents:\n{response.text}')
            raise MumbleException('Failed to make SNMP request')
        if json.get('code') != 200:
            self.logger.error(f'Manager {path} {method}: unexpected code {json.get("code")} (expected 200)')
            self.logger.debug(f'Response contents:\n{response.text}')
            raise MumbleException('Failed to make SNMP request')

        return_values = []
        for return_key, return_type in zip(return_keys, return_types):
            # must differentiate between missing key and key with value None
            has_value = return_key in json
            return_value = json.get(return_key)
            if not has_value or return_type is not None and not isinstance(return_value, return_type):
                self.logger.error(f'Manager {path} {method}: missing or unexpected value for {return_key} (expected {return_type}, got {return_value})')
                self.logger.debug(f'Response contents:\n{response.text}')
                raise MumbleException('Failed to make SNMP request')
            return_values.append(return_value)

        return return_values

    async def snmp_do_request_value(self, method: str, path: str, return_type: type | None, **kwargs):
        return_values = await self.snmp_do_request(method, path, ('value',), (return_type,), **kwargs)
        return return_values[0]

    async def snmp_get_var(self, secret: bytes, identifier: bytes | None = None) -> bytes:
        assert len(secret) == 8
        data = {'secret': secret.hex()}
        if identifier is not None:
            assert len(identifier) == 8
            data['identifier'] = identifier.hex()

        _, value = await self.snmp_do_request('get', '/manager/api/custom', ('identifier', 'value'), (str, str), params=data)
        try:
            value = binascii.a2b_base64(value.encode('ascii'), strict_mode=True)
        except (UnicodeEncodeError, binascii.Error):
            raise MumbleException('Invalid response from SNMP manager')
        return value

    async def snmp_set_var(self, secret: bytes, value: bytes) -> bytes:
        assert len(secret) == 8
        assert len(value) < 88
        data = {
            'secret': secret.hex(),
            'value': binascii.b2a_base64(value, newline=False).decode(),
        }
        identifier, value = await self.snmp_do_request('post', '/manager/api/custom', ('identifier', 'value'), (str, str), json=data)
        if len(identifier) != 16:
            self.logger.error(f'Invalid identifier from POST /manager/api/custom (length is {len(identifier)}, expected 16)')
            self.logger.debug(f'The invalid identifier is {identifier!r}')
            raise MumbleException('Failed to store custom SNMP value')

        try:
            return bytes.fromhex(identifier)
        except:
            self.logger.error(f'Invalid identifier from POST /manager/api/custom (not a hex-encoded string)')
            self.logger.debug(f'The invalid identifier is {identifier!r}')
            raise MumbleException('Failed to store custom SNMP value')

    async def snmp_get_raw(self, msg: bytes) -> bytes:
        data = {'data': msg.hex()}
        data = await self.snmp_do_request_value('get', '/manager/api/advanced', str, params=data)

        try:
            return bytes.fromhex(data)
        except:
            self.logger.error(f'Invalid data from GET /manager/api/advanced (not a hex-encoded string)')
            self.logger.debug(f'The invalid response is {data!r}')
            raise MumbleException('Invalid response from SNMP manager')

    async def snmp_get_monitoring(self, label: str) -> int:
        data = {'label': label}
        value = await self.snmp_do_request_value('get', '/manager/api/monitoring', str, params=data)
        try:
            return int(value)
        except ValueError:
            self.logger.error(f'Invalid value from GET /manager/api/monitoring (not an integer)')
            self.logger.debug(f'The invalid response is {value!r}')
            raise MumbleException('Invalid response from SNMP manager')

    async def snmp_get_user_monitoring(self, label: str) -> str | int | None:
        data = {'label': label}
        return await self.snmp_do_request_value('get', '/manager/api/monitoring_user', None, params=data)

    async def snmp_get_monitoring_init(self) -> dict[str, int]:
        return_values = await self.snmp_do_request('get', '/manager/api/monitoring_init', ('values',), (dict,))
        new_return_values = {}
        for label, value in return_values[0].items():
            try:
                new_return_values[label] = int(value)
            except ValueError:
                self.logger.error(f'Invalid value from GET /manager/api/monitoring_init (not an integer)')
                self.logger.debug(f'The invalid entry is {label!r}: {value!r}')
                raise MumbleException('Invalid response from SNMP manager')
        return new_return_values
