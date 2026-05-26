from contextlib import asynccontextmanager
from pathlib import Path

import asyncio
import os
import tempfile

from enochecker3 import MumbleException


def ssh_env(privkey_file):
    return {"GIT_SSH_COMMAND": f"ssh -i {privkey_file} -p 9201 -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -o IdentitiesOnly=yes"}


async def check_output(*args, **kwargs):
    child = await asyncio.create_subprocess_exec(*args, **kwargs, stdout=asyncio.subprocess.PIPE)
    (output, _) = await child.communicate()
    if child.returncode != 0:
        raise MumbleException("Failed to run git")
    return output


async def check_call(*args, **kwargs):
    child = await asyncio.create_subprocess_exec(*args, **kwargs)
    await child.wait()
    if child.returncode != 0:
        raise MumbleException("Failed to run git")


class GitWrapper:
    def __init__(self, path, privkey_path):
        self.path = Path(path)
        self.privkey_path = Path(privkey_path)

    async def write(self, fname, content):
        if Path(os.path.realpath(self.path / fname)) != (self.path / fname):
            raise MumbleException("Cannot write file")
        with open(self.path / fname, 'wb' if isinstance(content, bytes) else 'w') as f:
            f.write(content)

    async def read(self, fname):
        return await check_output("git", "show", f"HEAD:{fname}", cwd=self.path)

    async def add(self, fname):
        await check_call("git", "add", fname, cwd=self.path)

    async def commit(self, message, author, email):
        await check_call("git", "-c", f"user.name={author}", "-c", f"user.email={email}", "commit", "-m", message, cwd=self.path, env={"EMAIL": email})

    async def push(self):
        await check_call("timeout", "5s", "git", "push", cwd=self.path, env=ssh_env(self.privkey_path))


@asynccontextmanager
async def clone(privkey, url, path):
    with tempfile.NamedTemporaryFile(mode='w', delete_on_close = False) as privkey_file:
        privkey_file.write(privkey)
        privkey_file.close()
        try:
            proc = await asyncio.create_subprocess_exec("timeout", "5s", "git-wrapper", "git", "clone", url, path, env=ssh_env(privkey_file.name))
            await proc.wait()
            if proc.returncode != 0:
                raise MumbleException("failed to clone git repository")
            yield GitWrapper(path, privkey_file.name)
        finally:
            pass
