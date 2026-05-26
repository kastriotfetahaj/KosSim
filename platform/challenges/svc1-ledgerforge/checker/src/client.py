from __future__ import annotations

import base64
import os
import secrets
import string
from dataclasses import dataclass
from typing import Any

from enochecker3 import InternalErrorException, MumbleException
from httpx import AsyncClient, Response

ALPHABET = string.ascii_lowercase + string.digits


def noise_word(n: int = 12) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(n))


def service_secret() -> str:
    return os.environ.get("SERVICE_PUSH_SECRET", "rotate-secret")


def header_secret() -> dict[str, str]:
    return {"X-Checker-Secret": service_secret()}


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


async def ensure_status(r: Response, expected: int, what: str) -> None:
    if r.status_code != expected:
        raise MumbleException(f"{what}: expected {expected}, got {r.status_code} body={r.text[:200]}")


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


@dataclass
class Credentials:
    username: str
    password: str


def fresh_creds(prefix: str = "user") -> Credentials:
    return Credentials(username=f"{prefix}_{noise_word(10)}", password=noise_word(20))


async def register(client: AsyncClient, creds: Credentials) -> None:
    r = await client.post("/api/accounts/register", json={"username": creds.username, "password": creds.password})
    if r.status_code == 409:
        await login(client, creds)
        return
    await ensure_status(r, 200, "register")


async def login(client: AsyncClient, creds: Credentials) -> None:
    r = await client.post("/api/accounts/login", json={"username": creds.username, "password": creds.password})
    await ensure_status(r, 200, "login")
