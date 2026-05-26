import json
import socket
from pathlib import Path

from psutil._common import addr


class Client:
    def __init__(self, addr: str, port: int, db: str) -> None:
        self.addr = addr
        self.port = port
        self.db = db
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.io = socket.SocketIO(self.s, 'r')

    def __enter__(self) -> 'Client':
        self.s.connect((self.addr, self.port))
        self.send({'Select': {'database': self.db}})
        assert self.recv() == ([], "OK")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.s.close()

    def send(self, data: dict) -> None:
        self.s.send((json.dumps(data) + '\n').encode())

    def recv(self) -> tuple[list, str]:
        data = []
        while True:
            line = self.io.readline().decode()
            try:
                data.append(json.loads(line))
            except json.decoder.JSONDecodeError:
                line = line.strip()
                if line == 'undefined' or line.startswith('[debug]'):
                    data.append(line)
                else:
                    return data, line.strip()


def main() -> None:
    script = Path('../service/website/queries/api.qry').read_text()

    with Client('localhost', 9400, 'hCqPwdAXQkIS') as client:
        client.send({"Prepare": {"code": script}})
        resp, result = client.recv()
        print(resp, result)
        client.send({"Execute": {
            "code_ref": resp[-1]['code_ref'],
            "query": "get_value",
            "param": {"key": "9c5d3c64-ff17-488a-bcf7-47b679b9e5aa", "token": "7c0574f1-41a6-406e-8562-21dabf7e9bc5"}
        }})
        resp, result = client.recv()
        for r in resp:
            print('-', repr(r))
        print('=>', repr(result))



if __name__ == '__main__':
    main()
