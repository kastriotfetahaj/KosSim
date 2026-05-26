import os
import asyncio

from secrets import token_hex, randbits

from enochecker3 import (
    MumbleException,
    OfflineException
)


PORT_WINDOW = 120
BASE_PORT = 10000
PORT_POOL = None


def PASSWORD(): return randbits(64)

class CheckerExceptionTranslator:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Determine exception type and translate to checker error if necessary

        # Startup failure - attribute to remote service being down
        # TODO: sanity checks here that indeed remote connection was refused by
        # checking GR logs or something?
        if isinstance(exc_val, ConnectionRefusedError):
            raise OfflineException("failed to connect to service")

def get_port_pool():
    global PORT_POOL
    if PORT_POOL is None:
        PORT_POOL = asyncio.Queue()
        for x in range(PORT_WINDOW):
            PORT_POOL.put_nowait(BASE_PORT + PORT_WINDOW *
                                 int(os.environ["WORKER_ID"]) + x)
        print("Port pool initialized")
    return PORT_POOL


async def db_set(db, key, *vals):
    _vals = []
    for val in vals:
        _vals.append((str(val), isinstance(val, int)))
    await db.set(key, _vals)


async def db_get(db, key):
    _vals = []
    for val in await db.get(key):
        _vals.append(int(val[0]) if val[1] else val[0])
    return _vals
