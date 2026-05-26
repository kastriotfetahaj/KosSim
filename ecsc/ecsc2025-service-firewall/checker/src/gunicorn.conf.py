import json
import multiprocessing
import os
import socket
import subprocess
import typing

def get_bind_port() -> int:
    if (configured := os.getenv('CHECKER_PORT')) is not None:
        return int(configured)
    else:
        return 8100


def get_bind_addresses() -> typing.Generator[str, None, None]:
    if (explicit := os.getenv('CHECKER_BIND')) is not None:
        yield explicit
        return
    port = get_bind_port()
    # We need to ensure the checker is not reachable on the VPN interfaces.
    # Therefore, bind only to interfaces that exist currently.
    # Binding to their IPs would probably be sufficient, but this acts as
    # a defense-in-depth measure to avoid trouble with bad reverse path
    # filtering etc.
    interfaces = json.loads(subprocess.run(['ip', '-j', 'link'], check=True, stdout=subprocess.PIPE).stdout)
    for interface in interfaces:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, interface['ifname'].encode())
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        sock.bind(('::', port))
        sock.setblocking(False)
        yield f'fd://{sock.detach()}'


def get_worker_count() -> int:
    if (configured := os.getenv('CHECKER_WORKERS')) is not None:
        return int(configured)
    else:
        return min(8, multiprocessing.cpu_count())


worker_class = 'uvicorn.workers.UvicornWorker'
workers = get_worker_count()
bind = list(get_bind_addresses())
timeout = 90
keepalive = 3600
preload_app = True
