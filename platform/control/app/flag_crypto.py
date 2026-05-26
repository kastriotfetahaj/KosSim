"""Self-validating flag format, modelled on ECSC 2025 / saarCTF.

A flag is `FLAG{<32-char base64url>}`. The 24 bytes inside encode:

    struct {
        uint16_t tick;        // sequential tick (1, 2, ...)
        uint16_t team_id;     // target (defender) team id
        uint16_t service_id;
        uint16_t payload;     // flag-store / variant index
        uint8_t  mac[16];     // SHA256-HMAC of the 8 header bytes
    }

Validation is purely cryptographic: the submission endpoint never needs to
read the `flags` table to verify a flag's authenticity. The table is still
populated for audit, attack-info, and the local "current flag" UI.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import struct
from dataclasses import dataclass
from typing import Optional

from .config import required_env


FLAG_PREFIX = "FLAG"
MAC_LENGTH = 16
HEADER_LENGTH = 8
FLAG_BODY_LENGTH = HEADER_LENGTH + MAC_LENGTH  # 24 bytes -> 32 chars base64url
FLAG_INNER_CHARS = (FLAG_BODY_LENGTH * 4) // 3  # 32

# Tolerant matcher: accepts `=` padding chars too, but we always emit none.
FLAG_REGEX = re.compile(rf"{FLAG_PREFIX}\{{[A-Za-z0-9_\-=]{{{FLAG_INNER_CHARS},{FLAG_INNER_CHARS + 4}}}\}}")


@dataclass(frozen=True)
class FlagInfo:
    tick: int
    team_id: int
    service_id: int
    payload: int


def _secret_key() -> bytes:
    raw = required_env("SECRET_FLAG_KEY")
    if all(c in "0123456789abcdefABCDEF" for c in raw) and len(raw) % 2 == 0:
        try:
            return bytes.fromhex(raw)
        except ValueError:
            pass
    return hashlib.sha256(raw.encode()).digest()


def make_flag(tick: int, team_id: int, service_id: int, payload: int = 0) -> str:
    header = struct.pack(
        "<HHHH",
        tick & 0xFFFF,
        team_id & 0xFFFF,
        service_id & 0xFFFF,
        payload & 0xFFFF,
    )
    mac = hmac.new(_secret_key(), header, hashlib.sha256).digest()[:MAC_LENGTH]
    blob = header + mac
    body = base64.urlsafe_b64encode(blob).decode("ascii").rstrip("=")
    return f"{FLAG_PREFIX}{{{body}}}"


def decode_flag(flag: str) -> Optional[FlagInfo]:
    """Parse + verify a flag string. Returns None if not authentic.

    The body must be exactly ``FLAG_INNER_CHARS`` (32) characters of
    unpadded base64url — the canonical form ``make_flag()`` emits. Padded
    variants are rejected so the same logical flag cannot be re-submitted
    under different literal strings and bypass the per-flag dedup.
    """
    if not flag.startswith(FLAG_PREFIX + "{") or not flag.endswith("}"):
        return None
    body = flag[len(FLAG_PREFIX) + 1 : -1]
    if len(body) != FLAG_INNER_CHARS:
        return None
    try:
        blob = base64.urlsafe_b64decode(body.encode("ascii"))
    except Exception:
        return None
    if len(blob) != FLAG_BODY_LENGTH:
        return None
    header, mac = blob[:HEADER_LENGTH], blob[HEADER_LENGTH:]
    expected = hmac.new(_secret_key(), header, hashlib.sha256).digest()[:MAC_LENGTH]
    if not hmac.compare_digest(mac, expected):
        return None
    tick, team_id, service_id, payload = struct.unpack("<HHHH", header)
    return FlagInfo(tick=tick, team_id=team_id, service_id=service_id, payload=payload)


def flag_regex_pattern() -> str:
    return FLAG_REGEX.pattern
