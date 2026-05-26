"""Tests for the self-validating FLAG{} format."""

from __future__ import annotations

import re

import pytest

from ksapp.flag_crypto import (
    FLAG_BODY_LENGTH,
    FLAG_INNER_CHARS,
    FLAG_PREFIX,
    FLAG_REGEX,
    FlagInfo,
    decode_flag,
    flag_regex_pattern,
    make_flag,
)


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tick,team_id,service_id,payload",
    [
        (1, 1, 1, 0),
        (12345, 99, 7, 3),
        (0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF),  # max representable
        (0, 0, 0, 0),                       # min representable
        (7, 2, 5, 1),
    ],
)
def test_make_and_decode_roundtrip(tick, team_id, service_id, payload):
    flag = make_flag(tick, team_id, service_id, payload)
    info = decode_flag(flag)
    assert info == FlagInfo(
        tick=tick, team_id=team_id, service_id=service_id, payload=payload
    )


def test_flag_string_shape():
    flag = make_flag(42, 1, 2, 0)
    assert flag.startswith(FLAG_PREFIX + "{") and flag.endswith("}")
    body = flag[len(FLAG_PREFIX) + 1 : -1]
    # We always emit unpadded base64url -> 32 chars.
    assert len(body) == FLAG_INNER_CHARS
    assert "=" not in body


def test_regex_matches_generated_flag():
    flag = make_flag(99, 3, 5, 1)
    assert FLAG_REGEX.fullmatch(flag) is not None
    # The exported pattern should match too (used by the submission UI).
    assert re.fullmatch(flag_regex_pattern(), flag) is not None


@pytest.mark.parametrize("extra_pad", ["=", "==", "===", "===="])
def test_decode_rejects_padded_variants(extra_pad):
    """Regression: every padded form of a valid flag must be rejected.

    The regex stays lenient ({32,36} chars) so client-side matchers remain
    tolerant, but the decoder MUST be strict on the 32-char canonical form.
    Otherwise teams could submit `FLAG{xxx}`, `FLAG{xxx=}`, `FLAG{xxx==}`,
    ... and receive points multiple times — `flag_submit` deduplicates on
    the literal string, not on the decoded payload.
    """
    flag = make_flag(1, 1, 1, 0)
    padded = flag[:-1] + extra_pad + "}"
    # The regex is intentionally permissive…
    assert FLAG_REGEX.fullmatch(padded) is not None
    # …but the decoder must reject every non-canonical form.
    assert decode_flag(padded) is None


# ---------------------------------------------------------------------------
# Rejection paths
# ---------------------------------------------------------------------------


def test_decode_rejects_wrong_prefix():
    flag = make_flag(1, 1, 1, 0)
    swapped = "SSH" + flag[len(FLAG_PREFIX):]
    assert decode_flag(swapped) is None


def test_decode_rejects_truncated():
    flag = make_flag(1, 1, 1, 0)
    assert decode_flag(flag[:-2] + "}") is None


def test_decode_rejects_tampered_payload():
    flag = make_flag(1, 1, 1, 0)
    # Flip one char in the body so the HMAC fails.
    body = flag[len(FLAG_PREFIX) + 1 : -1]
    swap = "A" if body[5] != "A" else "B"
    tampered = (
        FLAG_PREFIX + "{" + body[:5] + swap + body[6:] + "}"
    )
    assert decode_flag(tampered) is None


def test_decode_rejects_empty():
    assert decode_flag("") is None
    assert decode_flag("FLAG{}") is None


def test_decode_rejects_garbage():
    assert decode_flag("not a flag at all") is None
    assert decode_flag("FLAG{!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!}") is None


def test_two_distinct_flags_have_distinct_macs():
    a = make_flag(1, 1, 1, 0)
    b = make_flag(1, 1, 1, 1)  # only payload differs
    assert a != b


def test_inner_length_is_consistent():
    assert FLAG_INNER_CHARS == (FLAG_BODY_LENGTH * 4) // 3
