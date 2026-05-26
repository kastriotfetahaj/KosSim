import json
import re
import requests
import signal
import subprocess
import time
import typing


FLAG_REGEX = re.compile(br'ECSC\{[A-Za-z0-9_-]{32}\}')


def register(host: str, username: str, password: str) -> requests.Session:
    session = requests.Session()
    response = session.post(f'http://{host}:9101/register', data={'username': username, 'password': password})
    assert response.ok
    return session


class VPN:
    def __init__(self, host: str, username: str, password: str) -> None:
        self.client = None
        self.host = host
        self.username = username
        self.password = password

    def connect(self) -> None:
        if self.client is None:
            self.client = subprocess.Popen(
                ['/sbin/vpn-client', self.host, '--username', self.username, '--password', self.password],
                stdout=subprocess.DEVNULL
            )
            connected = False
            while not connected:
                time.sleep(0.1)
                dump = json.loads(subprocess.check_output(['/sbin/ip', '-j', 'addr']))
                vpn = next((iface for iface in dump if iface['ifname'] == 'ecsc0'), None)
                if vpn is not None:
                    for addr in vpn.get('addr_info', []):
                        if addr.get('family') == 'inet6' and addr.get('local', '').startswith('fd00:ec5c'):
                            connected = True
                        if addr.get('family') == 'inet' and addr.get('local', '').startswith('10.'):
                            connected = True

    def disconnect(self) -> None:
        if self.client is not None:
            self.client.send_signal(signal.SIGINT)
            self.client.wait()
            self.client = None

    def __enter__(self) -> typing.Self:
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.disconnect()
