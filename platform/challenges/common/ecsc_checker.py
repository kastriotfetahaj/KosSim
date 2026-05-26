from __future__ import annotations

import json
import os
import random
import string
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests


class CheckerError(RuntimeError):
    status = "MUMBLE"


class Down(CheckerError):
    status = "DOWN"


class Corrupt(CheckerError):
    status = "CORRUPT"


def rnd(prefix: str, n: int = 10) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return f"{prefix}-" + "".join(random.choice(alphabet) for _ in range(n))


@dataclass
class Result:
    result: str
    body: dict[str, Any]


class EnoClient:
    def __init__(self, base: str, service: str, secret: str | None = None) -> None:
        self.base = base.rstrip("/")
        self.service = service
        self.secret = secret or os.environ.get("SERVICE_PUSH_SECRET", "rotate-secret")
        self.session = requests.Session()
        self.timeout = float(os.environ.get("SERVICE_HTTP_TIMEOUT", "5"))

    @property
    def headers(self) -> dict[str, str]:
        return {"X-Checker-Secret": self.secret, "Content-Type": "application/json"}

    def get(self, path: str, **kwargs: Any) -> requests.Response:
        try:
            res = self.session.get(f"{self.base}{path}", timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            raise Down(str(exc)) from exc
        if res.status_code >= 500:
            raise Down(f"http {res.status_code} on {path}")
        return res

    def post(self, path: str, **kwargs: Any) -> requests.Response:
        try:
            res = self.session.post(f"{self.base}{path}", timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            raise Down(str(exc)) from exc
        if res.status_code >= 500:
            raise Down(f"http {res.status_code} on {path}")
        return res

    def json_get(self, path: str, **kwargs: Any) -> dict[str, Any]:
        res = self.get(path, **kwargs)
        if res.status_code >= 400:
            raise CheckerError(f"http {res.status_code} on {path}")
        try:
            return res.json()
        except ValueError as exc:
            raise CheckerError(f"bad json on {path}") from exc

    def json_post(self, path: str, **kwargs: Any) -> dict[str, Any]:
        res = self.post(path, **kwargs)
        if res.status_code >= 400:
            raise CheckerError(f"http {res.status_code} on {path}")
        try:
            return res.json()
        except ValueError as exc:
            raise CheckerError(f"bad json on {path}") from exc

    def info(self) -> dict[str, Any]:
        body = self.json_get("/service", headers=self.headers)
        if body.get("serviceName") != self.service:
            raise CheckerError("service name mismatch")
        if int(body.get("flagVariants", 0)) < 2:
            raise CheckerError("missing flag variants")
        if int(body.get("noiseVariants", 0)) < 2:
            raise CheckerError("missing noise variants")
        if int(body.get("havocVariants", 0)) < 2:
            raise CheckerError("missing havoc variants")
        return body

    def task(self, method: str, tick: int, variant: int, flag: str | None = None, attack_info: str | None = None) -> Result:
        payload: dict[str, Any] = {
            "task_id": int(time.time() * 1000) & 0xFFFFFFFF,
            "method": method,
            "current_round_id": tick,
            "related_round_id": tick,
            "variant_id": variant,
            "timeout": 5000,
            "round_length": 60000,
            "flag": flag,
        }
        if attack_info is not None:
            payload["attack_info"] = attack_info
        body = self.json_post("/", headers=self.headers, json=payload)
        result = str(body.get("result", "MUMBLE"))
        if result not in {"OK", "MUMBLE", "DOWN", "CORRUPT", "INTERNAL_ERROR"}:
            raise CheckerError(f"bad result {result}")
        return Result(result=result, body=body)

    def require_ok(self, result: Result, what: str) -> None:
        if result.result != "OK":
            if result.result in {"DOWN", "INTERNAL_ERROR"}:
                raise Down(f"{what}: {result.body}")
            if result.result == "CORRUPT":
                raise Corrupt(f"{what}: {result.body}")
            raise CheckerError(f"{what}: {result.body}")

    def run_core(self) -> list[str]:
        self.info()
        attack_infos: list[str] = []
        tick = random.randint(10, 9000)
        for variant in (0, 1):
            flag = f"FLAG{{CHECK_{self.service.upper()}_{tick}_{variant}_{rnd('r', 6)}}}"
            put = self.task("PUTFLAG", tick, variant, flag)
            self.require_ok(put, "putflag")
            info = str(put.body.get("attack_info", ""))
            if not info:
                raise CheckerError("missing attack_info")
            attack_infos.append(info)
            get = self.task("GETFLAG", tick, variant, flag, info)
            self.require_ok(get, "getflag")
        for variant in (0, 1):
            self.require_ok(self.task("PUTNOISE", tick, variant), "putnoise")
            self.require_ok(self.task("GETNOISE", tick, variant), "getnoise")
            self.require_ok(self.task("HAVOC", tick, variant), "havoc")
        return attack_infos


def run(service: str, workflow: Callable[[EnoClient, list[str]], None]) -> int:
    base = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8080"
    random.seed(f"{service}:{base}:{time.time_ns()}")
    client = EnoClient(base, service)
    try:
        infos = client.run_core()
        workflow(client, infos)
    except CheckerError as exc:
        print(json.dumps({"status": exc.status, "message": str(exc)}))
        return 1
    print(json.dumps({"status": "OK", "service": service}))
    return 0
