from __future__ import annotations

import os
import random
import string
from typing import Any

from enochecker3 import MumbleException
from httpx import AsyncClient, Response


ALPHABET = string.ascii_lowercase + string.digits


def rnd(n: int = 10) -> str:
    return "".join(random.choice(ALPHABET) for _ in range(n))


def secret() -> str:
    return os.environ.get("SERVICE_PUSH_SECRET", "rotate-secret")


def header_secret() -> dict[str, str]:
    return {"X-Checker-Secret": secret(), "Content-Type": "application/json"}


async def ensure_status(response: Response, expected: int, what: str) -> None:
    if response.status_code != expected:
        raise MumbleException(f"{what}: http {response.status_code}")


async def json_or_mumble(response: Response, what: str) -> dict[str, Any]:
    try:
        return response.json()
    except ValueError as exc:
        raise MumbleException(f"{what}: bad json") from exc


async def post_task(
    client: AsyncClient,
    method: str,
    tick: int,
    variant: int,
    flag: str | None = None,
    attack_info: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "method": method,
        "current_round_id": tick,
        "related_round_id": tick,
        "variant_id": variant,
        "flag": flag,
        "timeout": 8000,
        "round_length": 60_000,
    }
    if attack_info is not None:
        payload["attack_info"] = attack_info
    response = await client.post("/", json=payload, headers=header_secret())
    await ensure_status(response, 200, f"{method} v{variant}")
    body = await json_or_mumble(response, f"{method} v{variant}")
    if str(body.get("result")) in {"DOWN", "INTERNAL_ERROR"} and method != "GETFLAG":
        raise MumbleException(f"{method} v{variant}: {body}")
    return body


async def fetch_session(client: AsyncClient) -> str:
    r = await client.get("/api/session/guest")
    await ensure_status(r, 200, "session.guest")
    body = await json_or_mumble(r, "session.guest")
    sess = str(body.get("session", ""))
    if "." not in sess or len(sess) < 16:
        raise MumbleException("session token shape drift")
    return sess
