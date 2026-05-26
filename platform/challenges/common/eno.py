"""Minimal ENO-compatible HTTP adapter used by KosSim challenge services."""

from __future__ import annotations

import os
import traceback
from typing import Callable, Optional

from flask import Flask, jsonify, request


_SERVICE_SECRET = os.environ["SERVICE_PUSH_SECRET"]

PutFlagCallback = Callable[[int, int, str], Optional[str]]
GetFlagCallback = Callable[[int, int, str], bool]
HavocCallback = Callable[[int, int], None]


def _auth_ok() -> bool:
    sent = request.headers.get("X-Checker-Secret", "")
    if sent and sent == _SERVICE_SECRET:
        return True
    return request.headers.get("X-Service-Secret", "") == _SERVICE_SECRET


def bind_eno(
    app: Flask,
    *,
    service_name: str,
    flag_variants: int,
    put_flag: PutFlagCallback,
    get_flag: GetFlagCallback,
    noise_variants: int = 0,
    havoc_variants: int = 0,
    havoc: Optional[HavocCallback] = None,
) -> None:
    @app.get("/service")
    def _eno_service():  # type: ignore[unused-ignore]
        if not _auth_ok():
            return jsonify({"error": "forbidden"}), 403
        return jsonify({
            "serviceName": service_name,
            "flagVariants": flag_variants,
            "noiseVariants": noise_variants,
            "havocVariants": havoc_variants,
        })

    @app.post("/")
    def _eno_task():  # type: ignore[unused-ignore]
        if not _auth_ok():
            return jsonify({"error": "forbidden"}), 403
        body = request.get_json(silent=True) or {}
        method = str(body.get("method") or "").upper()
        flag = body.get("flag")
        try:
            related_tick = int(body.get("related_round_id") or body.get("current_round_id") or 0)
        except (TypeError, ValueError):
            related_tick = 0
        try:
            payload = int(body.get("variant_id") or 0)
        except (TypeError, ValueError):
            payload = 0

        try:
            if method == "PUTFLAG":
                if not isinstance(flag, str) or not flag:
                    return jsonify({"result": "INTERNAL_ERROR", "message": "missing flag"})
                attack_info = put_flag(related_tick, payload, flag)
                return jsonify({"result": "OK", "attack_info": attack_info})
            if method == "GETFLAG":
                if not isinstance(flag, str) or not flag:
                    return jsonify({"result": "MUMBLE", "message": "missing flag"})
                return jsonify({"result": "OK" if get_flag(related_tick, payload, flag) else "MUMBLE"})
            if method == "HAVOC":
                if havoc is not None:
                    havoc(related_tick, payload)
                return jsonify({"result": "OK"})
            if method in ("PUTNOISE", "GETNOISE"):
                return jsonify({"result": "OK"})
            return jsonify({"result": "MUMBLE", "message": f"unknown method {method}"})
        except Exception as exc:  # pragma: no cover
            return jsonify({
                "result": "INTERNAL_ERROR",
                "message": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc(),
            })
