from __future__ import annotations

import asyncio
import json
import os
import secrets
import string
from dataclasses import dataclass
from typing import Any

from enochecker3 import MumbleException, InternalErrorException
from httpx import AsyncClient, Response


ALPHABET = string.ascii_lowercase + string.digits


def noise_word(length: int = 12) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def service_secret() -> str:
    return os.environ.get("SERVICE_PUSH_SECRET", "rotate-secret")


def header_secret() -> dict[str, str]:
    return {"X-Checker-Secret": service_secret()}


async def ensure_status(r: Response, expected: int, what: str) -> None:
    if r.status_code != expected:
        raise MumbleException(
            f"{what}: expected {expected}, got {r.status_code} body={r.text[:200]}"
        )


async def json_or_mumble(r: Response, what: str) -> dict[str, Any]:
    try:
        return r.json()
    except ValueError as exc:
        raise MumbleException(f"{what}: non-json body {r.text[:200]}") from exc


async def post_task(
    client: AsyncClient,
    method: str,
    tick: int,
    variant: int,
    flag: str | None = None,
    attack_info: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "task_id": secrets.randbits(31),
        "method": method,
        "current_round_id": tick,
        "related_round_id": tick,
        "variant_id": variant,
        "timeout": 8000,
        "round_length": 60000,
        "flag": flag,
    }
    if attack_info is not None:
        payload["attack_info"] = attack_info
    r = await client.post("/", json=payload, headers=header_secret())
    await ensure_status(r, 200, f"{method} v{variant}")
    body = await json_or_mumble(r, f"{method} v{variant}")
    result = str(body.get("result", "MUMBLE"))
    if result == "OK":
        return body
    if result in {"DOWN", "INTERNAL_ERROR"}:
        raise InternalErrorException(f"{method} v{variant}: {body.get('message')}")
    raise MumbleException(f"{method} v{variant}: {body}")


async def register(client: AsyncClient, username: str, password: str) -> dict[str, Any]:
    r = await client.post(
        "/api/accounts/register",
        json={"username": username, "password": password},
    )
    if r.status_code == 409:
        return await login(client, username, password)
    await ensure_status(r, 200, "register")
    return await json_or_mumble(r, "register")


async def login(client: AsyncClient, username: str, password: str) -> dict[str, Any]:
    r = await client.post(
        "/api/accounts/login",
        json={"username": username, "password": password},
    )
    await ensure_status(r, 200, "login")
    return await json_or_mumble(r, "login")


async def me(client: AsyncClient) -> dict[str, Any]:
    r = await client.get("/api/accounts/me")
    await ensure_status(r, 200, "me")
    return await json_or_mumble(r, "me")


@dataclass
class Credentials:
    username: str
    password: str


def fresh_creds(prefix: str = "user") -> Credentials:
    return Credentials(
        username=f"{prefix}_{noise_word(10)}",
        password=noise_word(20),
    )


async def with_timeout(coro: Any, seconds: float, label: str) -> Any:
    try:
        return await asyncio.wait_for(coro, timeout=seconds)
    except asyncio.TimeoutError as exc:
        raise MumbleException(f"{label}: timeout after {seconds}s") from exc
