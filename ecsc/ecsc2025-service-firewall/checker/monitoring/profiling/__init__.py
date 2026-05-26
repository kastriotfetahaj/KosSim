import asyncio
import datetime
import json
import multiprocessing
import pathlib
import queue
import typing

import fastapi
import pyinstrument
import pyinstrument.renderers
import pyinstrument.session

from checker import app as make_checker_app
checker_app = make_checker_app()


PROFILING_ENDPOINT = '/profile'

PROFILING_TMP_PATH = pathlib.Path('/tmp/profile-pending.json')
PROFILING_OUT_PATH = pathlib.Path('/tmp/profile-current.json')

class ResetToken:
    pass


def profile_worker(session_queue: multiprocessing.Queue):
    current: pyinstrument.session.Session | None = None
    last_write = datetime.datetime.now(datetime.UTC)
    while True:
        try:
            submission: pyinstrument.session.Session | ResetToken | None = session_queue.get(timeout=5)
        except queue.Empty:
            submission = None

        if isinstance(submission, ResetToken):
            current = None
            PROFILING_OUT_PATH.unlink()
            continue

        now = datetime.datetime.now(datetime.UTC)
        if current is not None:
            if submission is not None:
                current = pyinstrument.session.Session.combine(current, submission)
            if submission is None or now - last_write > datetime.timedelta(seconds=15):
                with PROFILING_TMP_PATH.open('w') as writer:
                    json.dump(current.to_json(), writer)
                PROFILING_TMP_PATH.rename(PROFILING_OUT_PATH) # Atomic rename
        elif submission is not None:
            current = submission
            last_write = now # Pretend we just wrote an empty file, so we only start writing after the first submission


def load_profile() -> str | None:
    if not PROFILING_OUT_PATH.is_file():
        return None
    with PROFILING_OUT_PATH.open('r') as reader:
        session = pyinstrument.session.Session.from_json(json.load(reader))
    return pyinstrument.renderers.HTMLRenderer().render(session)


# Global things here work because of preload_app in the gunicorn config
session_queue = multiprocessing.Queue()
worker = multiprocessing.Process(target=profile_worker, args=[session_queue])
worker.start()


@checker_app.get('/profile')
async def get_profile():
    html = await asyncio.get_running_loop().run_in_executor(None, load_profile)
    if html is None:
        return fastapi.responses.PlainTextResponse('No profile data yet, please be patient')
    return fastapi.responses.HTMLResponse(html)

@checker_app.get('/profile.json')
async def get_profile_json():
    if not PROFILING_OUT_PATH.is_file():
        return fastapi.responses.JSONResponse({}, status_code=409)
    return fastapi.responses.FileResponse(PROFILING_OUT_PATH, media_type='application/json')

@checker_app.post('/reset-profile')
async def reset_profile():
    session_queue.put(ResetToken())
    return fastapi.responses.Response(status_code=204)


@checker_app.middleware('http')
async def profiling_middleware(request: fastapi.Request, call_next: typing.Callable[[fastapi.Request], typing.Awaitable[fastapi.Response]]) -> fastapi.Response:
    if not request.url.path.startswith('/profile'):
        profiler = pyinstrument.Profiler()
        profiler.start()
        try:
            response = await call_next(request)
        finally:
            profiler.stop()
            if (session := profiler.last_session) is not None:
                session_queue.put(session)
        return response
    else:
        return await call_next(request)


app = lambda: checker_app
__all__ = ['app']
