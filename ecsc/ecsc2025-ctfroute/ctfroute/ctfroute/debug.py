import asyncio
import io
import logging
import os
import subprocess
import sys
from argparse import ArgumentParser, Namespace
from asyncio import AbstractEventLoop
from pathlib import Path

from ctfroute.utils import Backoff

LOGGER = logging.getLogger(__name__)

DEBUG_SOCK = Path("/tmp/ctfroute.sock")

_DID_ENTER_NAMESPACE = False


def enter_namespace():  # pragma: no cover
    """
    Create and enter namespaces to run tests without breaking host network.

    Used for testing / development: Creates and enters a network and user namespace in
    which the current user is mapped to root. This allows configuring network resources
    without screwing up the developers network settings.
    """
    global _DID_ENTER_NAMESPACE

    if _DID_ENTER_NAMESPACE:
        return

    print("Entering namespace...")

    uid = os.getuid()
    gid = os.getgid()

    if uid == 0 or gid == 0:
        return

    os.unshare(os.CLONE_NEWUSER | os.CLONE_NEWNET)

    f = os.open("/proc/self/uid_map", os.O_WRONLY)
    os.write(f, f"0 {uid} 1".encode("ASCII"))
    os.close(f)

    f = os.open("/proc/self/setgroups", os.O_WRONLY)
    os.write(f, b"deny")
    os.close(f)

    f = os.open("/proc/self/gid_map", os.O_WRONLY)
    os.write(f, f"0 {gid} 1".encode("ASCII"))
    os.close(f)
    _DID_ENTER_NAMESPACE = True


def _parse_debug_server(debug_server: str) -> tuple[str, int]:
    try:
        host, port_str = debug_server.rsplit(":", maxsplit=1)
        port = int(port_str)
        return host, port
    except ValueError as e:
        raise ValueError(
            f"'{debug_server}' is not a valid netloc for a debug server"
        ) from e


def debug_now(
    debug_server: str,
    namespaced: bool,
):  # pragma: no cover
    host, port = _parse_debug_server(debug_server)
    print(f"Expecting debugger to run on {host}:{port}")

    if namespaced:
        DEBUG_SOCK.unlink(missing_ok=True)
        # Forward from socket to debug server
        # This socat runs in parent namespace
        cmd = f"socat UNIX-LISTEN:{DEBUG_SOCK} TCP-Connect:{host}:{port}"
        subprocess.Popen(cmd.split(" "))
        enter_namespace()

        # Now we are namespaced and first need to bring up the loopback interface
        os.system("ip link set lo up")

        # Forward connections destined for loopback to the domain socket
        # This socat runs in the namespace created by unshare
        cmd = f"socat TCP-LISTEN:{port} UNIX-CONNECT:{DEBUG_SOCK}"
        subprocess.Popen(cmd.split(" "))

    import pydevd_pycharm

    pydevd_pycharm.settrace(
        host,
        port=port,
        stdout_to_server=True,
        stderr_to_server=True,
    )


async def debug_async(debug_server: str):
    import pydevd_pycharm

    host, port = _parse_debug_server(debug_server)
    backoff = Backoff(max_sec=20)

    stderr = sys.stderr
    while True:
        # intercept stderr because of annoying messages from pydevd_pycharm
        syserrbuff = io.StringIO()
        sys.stderr = syserrbuff
        try:
            pydevd_pycharm.settrace(
                host,
                port=port,
                stdout_to_server=True,
                stderr_to_server=True,
                suspend=False,
            )
            LOGGER.info(f"Debugger connected to {host}:{port}")
            return
        except ConnectionRefusedError:
            LOGGER.debug(
                f"Failed to connect to debugger on {host}:{port}, retrying in {backoff}"
            )
            await asyncio.sleep(next(backoff))

        except Exception as e:
            # Unexpected error, flush intercepted stderr
            syserrbuff.seek(0)
            stderr.write(syserrbuff.read())
            stderr.flush()
            raise e
        finally:
            sys.stderr = stderr


def add_debug_flags(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--namespaced",
        action="store_true",
        help="Drop into a namespace using unshare.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Connect to debugger.",
    )
    parser.add_argument(
        "--debug-blocking",
        action="store_true",
        help="Connect to debugger before doing anything else.",
    )
    parser.add_argument(
        "--debug-server",
        type=str,
        default="127.0.0.1:42424",
        help="Netloc of debug server, use with --debug or --debug-blocking.",
    )


def _noop_exception_handler(loop, context):
    """Set a breakpoint here to inspect uncaught exceptions."""
    loop.default_exception_handler(context)


def setup_debugging(args: Namespace, loop: AbstractEventLoop):
    if args.debug_blocking:
        # Explicit debug server
        loop.set_exception_handler(_noop_exception_handler)
        debug_now(debug_server=args.debug_server, namespaced=args.namespaced)
    elif args.debug and args.namespaced:
        # Namspaced and debug doesn't work with the async debug implementation
        loop.set_exception_handler(_noop_exception_handler)
        debug_now(debug_server=args.debug_server, namespaced=args.namespaced)
    elif args.debug:
        loop.set_exception_handler(_noop_exception_handler)
        loop.create_task(debug_async(args.debug_server))
    elif args.namespaced:
        # Only enter namespace, no debug
        enter_namespace()
