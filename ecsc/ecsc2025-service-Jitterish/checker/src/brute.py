import asyncio
import logging

from httpx import AsyncClient

from client import JitterishClient


async def x():
    aclient = AsyncClient(base_url='http://localhost:9400')
    client = JitterishClient(logging.LoggerAdapter(logging.getLogger('main')), aclient)
    await client.login('kUTnWmynIDlh', 'n9gGVJNjEbtV8dso')
    await client.logout()


async def main() -> None:
    logging.basicConfig(format=f'[%(asctime)s.%(msecs)03d] %(levelname)-9.9s: %(message)s', level=logging.INFO)
    for _ in range(100):
        await asyncio.gather(*[x() for _ in range(16)])


if __name__ == '__main__':
    asyncio.run(main())
