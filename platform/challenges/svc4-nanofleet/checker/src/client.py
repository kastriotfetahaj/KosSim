from __future__ import annotations

import base64
import hashlib
import hmac
import json
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
    result = str(body.get("result", "MUMBLE"))
    if result in {"DOWN", "INTERNAL_ERROR"} and method != "GETFLAG":
        raise MumbleException(f"{method} v{variant}: {result}")
    return body


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def hmac_sha256(key: bytes | str, data: bytes | str) -> bytes:
    if isinstance(key, str):
        key = key.encode("utf-8")
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hmac.new(key, data, hashlib.sha256).digest()


def encode_jwt(alg: str, kid: str | None, key: bytes | str, payload: dict[str, Any]) -> str:
    header: dict[str, Any] = {"alg": alg}
    if kid is not None:
        header["kid"] = kid
    header64 = b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload64 = b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signed = f"{header64}.{payload64}"
    sig = hmac_sha256(key, signed)
    return f"{signed}.{b64url(sig)}"
