#!/usr/bin/env python3
import argparse
import asyncio
import base64
import hashlib
import os
import pathlib
import secrets
import types
import typing

import httpx

from enochecker_core import (
    CheckerInfoMessage, CheckerMethod, CheckerResultMessage, CheckerTaskMessage, CheckerTaskResult
)

TIMEOUT = 60
ROUND_DURATION = 60

random = secrets.SystemRandom()

class CheckerClient:
    def __init__(self, url: str, service_address: str):
        self.service_address = service_address
        self.url = url.rstrip('/')
        if '://' not in self.url:
            self.url = 'http://' + self.url

        self._client = httpx.AsyncClient()
        self._metadata = None
        self._token = f'putflags-' + secrets.token_urlsafe(10)

    async def __aenter__(self) -> typing.Self:
        await self._client.__aenter__()
        response = await self._client.get(f'{self.url}/service')
        if response.status_code != 200:
            raise RuntimeError('Failed to get /service from checker')
        self._metadata = CheckerInfoMessage.model_validate_json(response.text)
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None = None,
                        exc_value: BaseException | None = None,
                        traceback: types.TracebackType | None = None) -> None:
        self._metadata = None
        await self._client.__aexit__(exc_type, exc_value, traceback)

    async def _request(self, message: CheckerTaskMessage) -> CheckerResultMessage:
        assert self._metadata, 'Client is not connected (did you forget `async with`)?'
        response = await self._client.post(
            self.url,
            content=message.model_dump_json(),
            headers={'Content-Type': 'application/json'},
            timeout=TIMEOUT,
        )
        assert response.status_code == 200, response.text
        result = CheckerResultMessage.model_validate_json(response.text)
        status = CheckerTaskResult(result.result)
        assert status == CheckerTaskResult.OK, response.text
        return result

    @staticmethod
    def generate_flag() -> str:
        return 'ENO' + base64.b64encode(secrets.token_bytes(36)).decode()

    def _build_putflag(self, *, flag: str | None, variant_id: int) -> CheckerTaskMessage:
        chain_id = f'putflag-{variant_id}-{self._token}'
        return CheckerTaskMessage(
            task_id=variant_id,
            method=CheckerMethod.PUTFLAG,
            address=self.service_address,
            team_id=0,
            team_name='putflag_victim',
            current_round_id=1,
            related_round_id=1,
            flag=flag,
            variant_id=variant_id,
            timeout=TIMEOUT * 1000,
            round_length=ROUND_DURATION * 1000,
            task_chain_id=chain_id,
            flag_regex=r'ENO[a-zA-Z0-9+/]{48}',
            flag_hash=hashlib.sha256(flag.encode()).hexdigest() if flag else None,
            attack_info=None
        )

    async def putflag(self, variant_id: int) -> tuple[str, str]:
        flag = self.generate_flag()
        message = self._build_putflag(
            flag=flag,
            variant_id=variant_id,
        )
        response = await self._request(message)
        return response.attack_info, flag

    @property
    def flag_stores(self) -> int:
        assert self._metadata, 'Client is not connected (did you forget `async with`)?'
        return self._metadata.flag_variants


async def put_flags(host: str, port: int, service: str):
    async with CheckerClient(f'http://{host}:{port}', service) as client:
        for flag_store in range(client.flag_stores):
            info, flag = await client.putflag(flag_store)
            print(f'{flag_store:2d} \x1b[32m{info:<32}\x1b[0m \x1b[2m{flag}\x1b[0m')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog='enochecker_putflag',
        description='Performs a single putflag step on a target service via the enochecker API'
    )
    # We want this to be as enochecker_test-compatible as we can make it.
    parser.add_argument(
        '-a', '--checker-address',
        help='The address on which the checker is listening (default: ENOCHECKER_CHECKER_ADDRESS)',
        default=os.environ.get('ENOCHECKER_CHECKER_ADDRESS')
    )
    parser.add_argument(
        '-n', '--checker-network',
        help='The name of the checker docker network to determine the IP from',
        default=os.environ.get('ENOCHECKER_CHECKER_NETWORK')
    )
    parser.add_argument(
        '-p', '--checker-port',
        help='The port on which the checker is listening (default: ENOCHECKER_CHECKER_PORT)',
        choices=range(1, 65536),
        metavar='{1..65535}',
        type=int,
        default=os.environ.get('ENOCHECKER_CHECKER_PORT')
    )
    parser.add_argument(
        '-A', '--service-address',
        help='The address on which the service is listening (default: ENOCHECKER_SERVICE_ADDRESS)',
        default=os.environ.get('ENOCHECKER_SERVICE_ADDRESS'),
    )
    parser.add_argument(
        '-N', '--service-network',
        help='The name of the service docker network to determine the IP from',
        default=os.environ.get('ENOCHECKER_SERVICE_NETWORK')
    )
    args = parser.parse_args()

    if args.service_network or args.checker_network:
        import docker

        client = docker.from_env()

        if args.service_network and not args.service_address:
            network = client.networks.get(args.service_network)
            args.service_address = network.attrs['IPAM']['Config'][0]['Gateway']

        if args.checker_network and not args.checker_address:
            network = client.networks.get(args.service_network)
            args.checker_address = network.attrs['IPAM']['Config'][0]['Gateway']


    if not args.checker_address:
        parser.error('Missing checker address, please set ENOCHECKER_CHECKER_ADDRESS')
    if not args.checker_port:
        parser.error('Missing checker port, please set ENOCHECKER_CHECKER_PORT')
    if not args.service_address:
        parser.error('Missing service address, please set ENOCHECKER_SERVICE_ADDRESS')

    asyncio.run(put_flags(
        args.checker_address,
        args.checker_port,
        args.service_address,
    ))

