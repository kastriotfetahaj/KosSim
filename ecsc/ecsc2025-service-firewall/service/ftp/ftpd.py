#!/usr/bin/env python3

import argon2
import argparse
import errno
import logging
import multiprocessing
import os
import pathlib
import psycopg
import signal
import shutil
import string
import time
import tomllib
import typing

from pyftpdlib.authorizers import AuthenticationFailed, DummyAuthorizer
from pyftpdlib.filesystems import AbstractedFS, FilesystemError
from pyftpdlib.handlers import TLS_DTPHandler, TLS_FTPHandler, _FileReadWriteError, logger
from pyftpdlib.servers import MultiprocessFTPServer

PLACEHOLDER_HASH = '$argon2id$v=19$m=65536,t=3,p=4$hN4NOrS83O5jXmamabBa/w$9050fW10rg0Mh1GYQK4jGGUHteR2Pj0kGN/3eXpk/wo' # argon2(b'')


class Config:
    '''Nicer access to config parameters'''

    def __init__(self, data: dict[str, typing.Any]):
        self._data = data

    def __getitem__(self, key: str) -> typing.Any:
        current = self._data
        for entry in key.split('.'):
            current = current.get(entry, None)
            if current is None:
                break
        return current

    def apply(self, path: str, on: typing.Any, exclude: set[str] = set()) -> typing.Any:
        settings = self[path]
        if settings is not None:
            if not isinstance(settings, dict):
                raise TypeError(f'Attempting to apply {settings} (not a dictionary)')
            for key, value in settings.items():
                if key not in exclude:
                    setattr(on, key, value)
        return on


class PgsqlAuthorizer(DummyAuthorizer):
    '''PostgreSQL-based authorizer'''

    def __init__(self, connection: str, query: str, root: pathlib.Path):
        # Explicitly not calling super().__init__ / setting user_table, since that should not be used.
        assert connection is not None
        assert query is not None
        self.connection_string = connection
        self.query = query
        self.root = root
        self.hasher = None

    def __getstate__(self):
        return {
            # Don't persist the DB across processes
            'connection': self.connection_string,
            'query': self.query,
            'root': self.root,
        }

    def __setstate__(self, state):
        self.__init__(**state)

    @staticmethod
    def is_valid_username(username: str) -> bool:
        if len(username) > 64:
            return False
        if any(char not in string.ascii_letters + string.digits + '-_' for char in username):
            return False
        return True

    def validate_authentication(self, username, password, handler):
        if not PgsqlAuthorizer.is_valid_username(username):
            raise AuthenticationFailed('Invalid username')
        if not isinstance(password, str):
            raise TypeError('Weird password type')
        if self.hasher is None:
            self.hasher = argon2.PasswordHasher(time_cost=1, memory_cost=4096, parallelism=1)
        try:
            with psycopg.connect(self.connection_string, autocommit=True) as db:
                with db.cursor() as cursor:
                    # NB: typing would have us believe this is an SQLi sink (because self.query is dynamic)
                    # But actually that's just from the configuration, not from user input.
                    cursor.execute(self.query, (username,)) # pyright: ignore
                    row = cursor.fetchone()
                    actual_hash = row[0] if row is not None else None
            verify_hash = actual_hash if actual_hash is not None else PLACEHOLDER_HASH
            if not isinstance(verify_hash, (str, bytes)):
                raise TypeError('Database did not return password hash as string or bytes')
            try:
                self.hasher.verify(verify_hash, password)
                if actual_hash is None:
                    raise AuthenticationFailed('Unknown user or incorrect password')
            except argon2.exceptions.VerifyMismatchError:
                raise AuthenticationFailed('Unknown user or incorrect password')
        except AuthenticationFailed:
            raise
        except:
            logging.exception('Database failed')
            raise AuthenticationFailed('Authentication backend failure')

    def get_home_dir(self, username):
        home: pathlib.Path = self.root / username
        home.mkdir(parents=True, exist_ok=True)
        return str(home)

    def has_perm(self, username, perm, path=None):
        return perm in self.get_perms(username)

    def get_perms(self, username):
        return 'elradfmwT' # Everything except SITE CHMOD, which I don't trust.

    def get_msg_login(self, username):
        return 'Logged in.'

    def get_msg_quit(self, username):
        return 'Goodbye.'


# TODO: In MKD etc. this should trigger a different return code, but this is good enough for now.
class OutOfQuota(FilesystemError, _FileReadWriteError):
    '''Quota errors'''
    errno = errno.ENOSPC
    def __str__(self):
        return 'Disk quota allocation exceeded'


class QuotaDTPHandler(TLS_DTPHandler):
    '''Quota-enforcing DTP handler (ensures that single-file uploads don't exceed the quota)'''

    def __init__(self, sock, cmd_channel):
        super().__init__(sock, cmd_channel)
        self.disk_quota = self.cmd_channel.get_disk_quota()
        self.available = self.disk_quota or 0

    def recv(self, buffer_size):
        chunk: bytes = super().recv(buffer_size)
        # NOTE: This is the quota sanity checking.
        self.available -= len(chunk)
        if self.available < 0 and self.disk_quota is not None:
            self._resp = ('552 Exceeded storage allocation', logger.info)
            self.close()
            return b''
        return chunk

    def use_sendfile(self):
        return False # sendfile seems broken, and I can't be bothered to fix it.


class QuotaFTPHandler(TLS_FTPHandler):
    '''Quota-enforcing FTP handler (provides infrastructure for QuotaDTPHandler and QuotaAbstractedFS)'''

    disk_quota: int | None = None # Quota, in bytes
    entry_quota: int | None = None # Maximum number of file system entries

    def get_disk_quota(self) -> int | None:
        override = getattr(self.authorizer, 'get_disk_quota', lambda _: None)(self.username)
        return override if override is not None else self.disk_quota

    def get_entry_quota(self) -> int | None:
        override = getattr(self.authorizer, 'get_entry_quota', lambda _: None)(self.username)
        return override if override is not None else self.entry_quota

    def close(self) -> None:
        super().close()
        if (cleanup := getattr(self.authorizer, 'close', None)):
            cleanup()


class QuotaWrappedFile:
    '''Wrapper around a file object that tracks quota in a QuotaAbstractedFS'''

    def __init__(self, fs, underlying):
        self._fs = fs
        self._underlying = underlying

    def __getattr__(self, attr):
        return getattr(self._underlying, attr)

    def fileno(self):
        # No reopening this some other way
        # This must be ValueError so the use_sendfile() handling works.
        raise ValueError('QuotaWrappedFile does not allow accessing fileno()')

    def truncate(self, size=None):
        # Can only acquire quota by truncating until the recalculate happens
        current = self._underlying.tell()
        new_size = size if size is not None else current
        self._fs.quota_acquire(storage=max(0, new_size - current))
        self._underlying.truncate(size)

    def writelines(self, lines):
        self._fs.quota_acquire(storage=sum(len(line) for line in lines))
        self._underlying.writelines(lines)

    def write(self, b):
        self._fs.quota_acquire(storage=len(b))
        self._underlying.write(b)

    def close(self):
        if self._underlying is not None:
            self._underlying.close()
            self._underyling = None
            self._fs.quota_recalculate()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class QuotaAbstractedFS(AbstractedFS):
    '''Quota-enforcing file system'''

    def __init__(self, root, cmd_channel):
        super().__init__(root, cmd_channel)
        self.disk_quota: int | None = getattr(self.cmd_channel, 'get_disk_quota', lambda: None)()
        self.entry_quota: int | None = getattr(self.cmd_channel, 'get_entry_quota', lambda: None)()
        self.disk_used: int = 0
        self.entries_used: int = 0
        self.quota_recalculate(check=False) # Don't error in construction if quota is exceeded.

    def quota_acquire(self, *, storage: int = 0, entries: int = 0):
        if storage and self.disk_quota is not None:
            if self.disk_used + storage > self.disk_quota:
                raise OutOfQuota()
            self.disk_used += storage
        if entries and self.entry_quota is not None:
            if self.entries_used + entries > self.entry_quota:
                raise OutOfQuota()
            self.entries_used += entries

    def quota_release(self, *, storage: int = 0, entries: int = 0):
        if storage and self.disk_quota is not None:
            self.disk_used -= storage
        if entries and self.entry_quota is not None:
            self.entries_used -= entries

    def quota_recalculate(self, check: bool = True):
        '''Recalculate quota used in this tree'''
        # This might race with other modifications. In any case, this is a best-effort thing
        # so that the server doesn't run out of disk space, so :shrug:.
        entries = 0
        storage = 0
        for directory, _, files in os.walk(self.root):
            entries += 1 + len(files)
            for name in files:
                path = pathlib.Path(directory) / name
                try:
                    if path.is_file():
                        storage += path.stat().st_size
                except FileNotFoundError:
                    continue # That's fine, see the race note.
        self.disk_used = storage
        self.entries_used = entries
        if check and self.disk_quota is not None and self.disk_used > self.disk_quota:
            raise OutOfQuota()
        if check and self.entry_quota is not None and self.entries_used > self.entry_quota:
            raise OutOfQuota()

    def quota_wrap(self, fileobj):
        '''Wrap a file object for quota enforcement'''
        if not fileobj.writable():
            return fileobj # Not writable, no tracking needed
        else:
            return QuotaWrappedFile(self, fileobj)

    def open(self, filename, mode):
        entries = 1 if not pathlib.Path(filename).exists() else 0
        self.quota_acquire(entries=entries)
        try:
            return self.quota_wrap(super().open(filename, mode))
        except:
            self.quota_release(entries=entries)
            raise

    def mkdir(self, path):
        self.quota_acquire(entries=1)
        try:
            super().mkdir(path)
        except:
            self.quota_release(entries=1)
            raise

    def rmdir(self, path):
        super().rmdir(path)
        self.quota_release(entries=1)

    def remove(self, path):
        super().remove(path)
        self.quota_recalculate() # Can't know for sure how much quota we released.

    def mkstemp(self, suffix='', prefix='', dir=None, mode='wb'): # pyright: ignore (return type)
        self.quota_acquire(entries=1)
        try:
            return self.quota_wrap(super().mkstemp(suffix, prefix, dir, mode))
        except:
            self.quota_release(entries=1)
            raise


def cleanup_task(root: pathlib.Path, interval: int, maximum_age: int):
    while True:
        now = time.time()
        try:
            for subdirectory in root.iterdir():
                try:
                    if not subdirectory.is_dir():
                        continue
                    # This is not around on Linux (yet), and also not all file systems expose this.
                    # Fall back to atime/ctime/mtime if we have to.
                    # See https://github.com/python/cpython/issues/83714
                    stat = subdirectory.stat()
                    birth_time = getattr(stat, 'st_birthtime', None)
                    if birth_time is None:
                        birth_time = min(stat.st_atime, stat.st_ctime, stat.st_mtime)
                    age = now - birth_time
                    if age > maximum_age:
                        try:
                            shutil.rmtree(subdirectory)
                            logging.info(f'Removed {subdirectory} ({age} seconds old)')
                        except:
                            logging.exception(f'Failed to remove {subdirectory} ({age} seconds old)')
                except:
                    logging.exception(f'Failed to check whether cleanup is needed for {subdirectory}')
        except:
            logging.exception(f'Failed to iterate over the storage directory')
        time.sleep(interval)


if __name__ == '__main__':
    # Parse command line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', help='Configuration file to load', type=pathlib.Path,
                                    default=pathlib.Path('/etc/ftpd.toml'))
    parser.add_argument('--log-level', help='Log level', type=str, default='warning')
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level.upper())

    # Load the configuration
    with args.config.open('rb') as config_file:
        config = Config(tomllib.load(config_file))

    # Set up authentication
    connection = config['auth.connection']
    if '__PASSWORD__' in connection:
        file = config['auth.password_file'] or os.getenv('DB_PASSWORD_FILE')
        if file is not None:
            password = pathlib.Path(file).read_text().strip()
        else:
            password = os.getenv('DB_PASSWORD')
        if password is None:
            raise ValueError('__PASSWORD__ in the connection string, but no password provided')
        connection = connection.replace('__PASSWORD__', password)

    authorizer = PgsqlAuthorizer(
        connection=connection,
        query=config['auth.query'],
        root=pathlib.Path(config['auth.root'])
    )

    # Set up data connection handling
    dtp = config.apply('data', QuotaDTPHandler)

    # Set up file system
    fs = QuotaAbstractedFS

    # Set up FTP connection handling
    handler = config.apply('ftp', QuotaFTPHandler)
    handler.dtp_handler = dtp
    handler.authorizer = authorizer
    handler.abstracted_fs = fs

    # Start the cleanup task
    multiprocessing.Process(
        target=cleanup_task,
        args=(
            pathlib.Path(config['auth.root']),
            int(config['data.cleanup_interval']),
            int(config['data.maximum_age'])
        ),
        daemon=True
    ).start()

    # Start the server
    host = config['server.host'] or '::'
    port = config['server.port'] or 21
    backlog = config['server.backlog'] or 2048

    shutdown = multiprocessing.Event()
    def handle_sigint(signo: int, stack_frame) -> None:
        '''Ensures a graceful exit on SIGINT'''
        # This normally works by default, but we need to distinguish
        # explicitly requested exits from those caused by an error.
        logging.info('Received SIGINT, shutting down...')
        shutdown.set()
        raise KeyboardInterrupt()
    signal.signal(signal.SIGINT, handle_sigint)

    server = MultiprocessFTPServer((host, port), handler, backlog=backlog)
    server = config.apply('server', server, exclude={'host', 'port', 'backlog'})
    server.serve_forever()

    if not shutdown.is_set():
        logging.warning('Shutdown was not explicitly requested')
        exit(1)
