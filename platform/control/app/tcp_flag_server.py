"""Line-delimited TCP flag submission (ECSC port 1337 protocol subset)."""

from __future__ import annotations

import asyncio
import os
from typing import Optional

from .db import get_cursor
from .flag_crypto import FLAG_PREFIX
from .flag_submit import (
    TCP_STATUS_LINES,
    resolve_submitter_by_ip,
    resolve_submitter_by_token,
    submit_flags,
)


def _tcp_port() -> int:
    return int(os.getenv("FLAG_TCP_PORT", "1337"))


def _tcp_enabled() -> bool:
    return os.getenv("FLAG_TCP_ENABLED", "1") not in ("0", "false", "False", "")


async def _handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer = writer.get_extra_info("peername")
    source_ip = peer[0] if peer else "unknown"
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip("\r\n")
            if not text.strip():
                continue

            submitter_id: Optional[int] = None
            flag_line = text.strip()

            # Optional auth line: submit-team1 or full token
            if not flag_line.startswith(FLAG_PREFIX):
                with get_cursor(commit=False) as (_conn, cur):
                    submitter_id = resolve_submitter_by_token(cur, flag_line)
                    if submitter_id is None:
                        submitter_id = resolve_submitter_by_ip(cur, source_ip)
                if submitter_id is None:
                    writer.write(TCP_STATUS_LINES["bad_ip"].encode())
                    await writer.drain()
                    continue
                line2 = await reader.readline()
                if not line2:
                    break
                flag_line = line2.decode("utf-8", errors="replace").rstrip("\r\n").strip()
            else:
                with get_cursor(commit=False) as (_conn, cur):
                    submitter_id = resolve_submitter_by_ip(cur, source_ip)
                    if submitter_id is None:
                        token = os.getenv("TEAM_SUBMIT_DEFAULT_TOKEN", "").strip()
                        if token:
                            submitter_id = resolve_submitter_by_token(cur, token)

            if submitter_id is None:
                writer.write(TCP_STATUS_LINES["bad_ip"].encode())
                await writer.drain()
                continue

            if not flag_line.startswith(FLAG_PREFIX + "{"):
                writer.write(TCP_STATUS_LINES["bad_format"].encode())
                await writer.drain()
                continue

            try:
                result = await asyncio.to_thread(
                    submit_flags,
                    submitter_team_id=submitter_id,
                    flags=[flag_line],
                    source_ip=source_ip,
                    require_running=True,
                )
            except Exception:
                writer.write(b"[ERR] Internal error\n")
                await writer.drain()
                continue

            if result.get("offline"):
                writer.write(TCP_STATUS_LINES["offline"].encode())
            elif result["results"]:
                writer.write(result["results"][0]["tcp_line"].encode())
            else:
                writer.write(TCP_STATUS_LINES["bad_format"].encode())
            await writer.drain()
    except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def run_tcp_server() -> asyncio.Server:
    return await asyncio.start_server(_handle_client, host="0.0.0.0", port=_tcp_port())


_server: Optional[asyncio.Server] = None


def start_tcp_server_background() -> None:
    """Start TCP listener in a daemon thread (called from FastAPI startup)."""
    if not _tcp_enabled():
        return

    def _run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _main() -> None:
            global _server
            _server = await run_tcp_server()
            print(f"[tcp-submit] listening on 0.0.0.0:{_tcp_port()}", flush=True)
            async with _server:
                await _server.serve_forever()

        loop.run_until_complete(_main())

    import threading

    thread = threading.Thread(target=_run, name="tcp-flag-submit", daemon=True)
    thread.start()
