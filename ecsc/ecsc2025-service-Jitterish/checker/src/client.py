import asyncio
import random
import json
import html
import json
import logging
import re
from logging import LoggerAdapter
from typing import Callable, Any, Literal

from enochecker3 import MumbleException
from httpx import AsyncClient, Response


class JitterishClient:
    def __init__(self, logger: LoggerAdapter, client: AsyncClient) -> None:
        self.logger = logger
        self.client = client

    def _assert_status_code(self, r: Response, code: int = 200, parse: Callable[[str], str] | None = None) -> None:
        if r.status_code == code:
            return
        errlog = r.text
        if parse is not None:
            errlog = parse(errlog)
        self.logger.error(f"Bad status code during {r.request.method} {r.request.url.path}: " \
                          + f"({r.status_code} != {code})\n{errlog}")
        raise MumbleException(f"{r.request.method} {r.request.url.path} failed")

    async def get(self, url: str, code: int = 200, **kwargs: Any) -> Response:
        response = await self.client.get(url, **kwargs)
        # self.logger.info(f'{response.request.method} {url} => {response.status_code}')
        self._assert_status_code(response, code)
        return response

    async def post(self, url: str, code: int = 200, **kwargs: Any) -> Response:
        response = await self.client.post(url, **kwargs)
        # self.logger.info(f'{response.request.method} {url} => {response.status_code}')
        self._assert_status_code(response, code)
        return response

    def find_error_alerts(self, text: str) -> list[str]:
        return re.findall('class="alert alert-error".*?>(.*?)(?:</div>|</p>)', text)

    def log_error_alerts(self, response: Response) -> None:
        alerts = self.find_error_alerts(response.text)
        if alerts:
            self.logger.warning(f'Error alerts found on {response.url}: {alerts}')

    async def register(self, username: str, password: str, first: str, last: str,
                       account_type: Literal['community', 'business', 'enterprise'], custom: str=None) -> None:
        await self.get('/session/register')
        status_data = {}
        status_data["num_reports"] = random.randrange(0,10)
        status_data["salary"] = random.randrange(0,100000)
        if custom:
            status_data["custom"] = custom
        response = await self.post('/session/register', data={
            'username': username, 'password': password,
            'firstname': first, 'lastname': last,
            'account_type': account_type,
            'status':json.dumps(status_data)
        }, follow_redirects=True)
        self.log_error_alerts(response)
        if response.url.path != '/session/profile':
            self.logger.warning(f'Unexpected redirect to {response.url} after registration of {username}')
            raise MumbleException('Registration failed')
        self.logger.info(f'Registered {username!r} (password {password!r})')


    async def register_raw(self, username: str, password: str, first: str, last: str,
                           account_type: Literal['community', 'business', 'enterprise'],
                           custom: str, num_reports: int, looking_for_job: bool, current_salary: int) -> None:
        await self.get('/session/register')
        status_data = {}
        if num_reports is not None:
            status_data["num_reports"] = num_reports
        if looking_for_job is not None:
            status_data["looking_for_job"] = looking_for_job
        if current_salary is not None:
            status_data["current_salary"] = current_salary 
        if custom is not None:
            status_data["custom"] = custom
        # only custom gives us a string as input
        if custom and not num_reports and not looking_for_job and not current_salary:
            status_data = custom
        response = await self.post('/session/register', data={
            'username': username, 'password': password,
            'firstname': first, 'lastname': last,
            'account_type': account_type,
            'status':json.dumps(status_data)
        }, follow_redirects=True)
        self.log_error_alerts(response)
        if response.url.path != '/session/profile':
            self.logger.warning(f'Unexpected redirect to {response.url} after registration of {username}')
            self.logger.info(self.find_error_alerts(response.text))
            raise MumbleException('Registration failed')
        self.logger.info(f'Registered {username!r} (password {password!r})')


    async def login(self, username: str, password: str) -> None:
        await self.get('/session/login')
        response = await self.post('/session/login', data={
            'username': username, 'password': password,
        }, follow_redirects=True)
        self.log_error_alerts(response)
        if 'Invalid username' in response.text or 'Invalid password' in response.text:
            raise MumbleException('Login failed (username/password not accepted)')
        if response.url.path != '/session/profile':
            self.logger.warning(f'Unexpected redirect to {response.url} after login')
            raise MumbleException('Login failed')
        self.logger.info(f'Logged in as {username!r} (password {password!r})')

    async def logout(self) -> None:
        await self.post('/session/logout', follow_redirects=True)

    # assumes that reporter is logged in
    async def report(self, username, reason) -> Response:
        response = await self.post('/support', data={
            'target_user': username, 'description': reason,
        }, follow_redirects=True)
        self.log_error_alerts(response)
        return response

    async def list_customers(self) -> dict[str, list[str]]:
        response = await self.get('/customers')
        self.log_error_alerts(response)
        return {
            'community': re.findall(r'href="/database/(\w+)"', response.text),
            'enterprise': re.findall(r'href="/api/(\w+)/keys/all"', response.text)
        }

    async def db_list_collections(self, db: str) -> list[str]:
        response = await self.get(f'/database/{db}')
        collections = re.findall(r'<li data-role="collection">\s*([A-Za-z0-9_]*)', response.text)
        self.logger.info(f'Collections in {db}: {collections}')
        return collections

    async def db_append(self, db: str, collection: str, data: Any) -> None:
        self.logger.info(f'Appending to {db}/{collection}: {json.dumps(data)}')
        response = await self.post(f'/database/{db}/append', data={'collection': collection, 'data': json.dumps(data)})
        self.log_error_alerts(response)
        if 'successfully appended' not in response.text:
            raise MumbleException('Failed to append to database')

    async def db_query(self, db: str, code: str, query_name: str, param: Any) -> list[Any]:
        self.logger.info(f'Querying {db} with {query_name}({param})')
        response = await self.post(f'/database/{db}/customquery',
                                   data={'query': code, 'query_name': query_name, 'params': json.dumps(param)})
        self.log_error_alerts(response)
        if 'class="alert alert-error"' in response.text:
            raise MumbleException('Failed to query database')

        raw_output = re.findall('<p data-role="output">(.*?)</p>', response.text)
        raw_output = [html.unescape(_) for _ in raw_output]
        self.logger.info(f'Query output: {"\n".join(raw_output)}')
        try:
            return [json.loads(_) for _ in raw_output]  # TODO how to handle error messages
        except json.JSONDecodeError:
            raise MumbleException('Query output is no valid JSON')

    async def api_create(self, database: str, data: Any) -> str:
        response = await self.post(f'/api/{database}/create', json=data)
        self.logger.info(f'KV stored {data} => {response.json()}')
        return response.json()['key']

    async def api_grant(self, database: str, key: str, token: str) -> bool:
        response = await self.post(f'/api/{database}/grant/{key}/{token}')
        self.logger.info(f'KV granted {token} on {key} => {response.json()}')
        return response.json()['ok']

    async def api_get(self, database: str, what: str = 'keys', key: str = 'all', token: str | None = None) -> Any:
        response = await self.get(f'/api/{database}/{what}/{key}', params={'token': token} if token else {})
        self.logger.info(f'KV fetched {what} on {key} => {response.json()}')
        return response.json()




async def main() -> None:
    logging.basicConfig(format=f'[%(asctime)s.%(msecs)03d] %(levelname)-9.9s: %(message)s', level=logging.INFO)
    aclient = AsyncClient(base_url='http://localhost:9400')
    client = JitterishClient(logging.LoggerAdapter(logging.getLogger('main')), aclient)
    await client.register('test', 'test', 'First', 'Last', 'community')


if __name__ == '__main__':
    asyncio.run(main())
