"""Tests for the checker status combinators in eno_checker."""

from __future__ import annotations

import pytest

from ksapp.eno_checker import (
    derive_method_statuses,
    downgrade,
    is_active,
    is_up,
    normalize,
)


# ---------------------------------------------------------------------------
# Status ladder
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "current,new,expected",
    [
        # downgrade never makes things better.
        ("SUCCESS", "MUMBLE", "MUMBLE"),
        ("MUMBLE", "SUCCESS", "MUMBLE"),
        ("SUCCESS", "OFFLINE", "OFFLINE"),
        ("MUMBLE", "OFFLINE", "OFFLINE"),
        ("RECOVERING", "MUMBLE", "MUMBLE"),
        ("RECOVERING", "SUCCESS", "RECOVERING"),
        ("CRASHED", "OFFLINE", "CRASHED"),
        # Idempotent.
        ("SUCCESS", "SUCCESS", "SUCCESS"),
    ],
)
def test_downgrade(current, new, expected):
    assert downgrade(current, new) == expected


def test_downgrade_unknown_new_treated_as_mumble():
    assert downgrade("SUCCESS", "WHATEVER") == "MUMBLE"
    # Worse-than-MUMBLE wins.
    assert downgrade("OFFLINE", "WHATEVER") == "OFFLINE"


def test_downgrade_unknown_current_returns_new():
    assert downgrade("UNKNOWN", "MUMBLE") == "MUMBLE"


def test_full_ladder_ordering():
    """Combining all worsening statuses always ends at the worst one."""
    chain = ["SUCCESS", "RECOVERING", "MUMBLE", "OFFLINE", "TIMEOUT", "CRASHED"]
    cur = "SUCCESS"
    for s in chain:
        cur = downgrade(cur, s)
    assert cur == "CRASHED"


# ---------------------------------------------------------------------------
# Normalisation from eno result strings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("OK", "SUCCESS"),
        ("SUCCESS", "SUCCESS"),
        ("MUMBLE", "MUMBLE"),
        ("FLAGMISSING", "FLAGMISSING"),
        ("OFFLINE", "OFFLINE"),
        ("TIMEOUT", "TIMEOUT"),
        ("INTERNAL_ERROR", "CRASHED"),
        ("anything-else", "MUMBLE"),
        ("", "MUMBLE"),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


# ---------------------------------------------------------------------------
# is_up / is_active
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status,expected",
    [
        ("SUCCESS", True),
        ("RECOVERING", True),
        ("MUMBLE", False),
        ("FLAGMISSING", False),
        ("OFFLINE", False),
        ("CRASHED", False),
        ("TIMEOUT", False),
        ("", False),
    ],
)
def test_is_up(status, expected):
    assert is_up(status) is expected


@pytest.mark.parametrize(
    "status,expected",
    [
        ("SUCCESS", True),
        ("RECOVERING", True),
        ("MUMBLE", True),
        ("FLAGMISSING", True),
        ("OFFLINE", False),
        ("TIMEOUT", False),
        ("CRASHED", False),
    ],
)
def test_is_active(status, expected):
    assert is_active(status) is expected


# ---------------------------------------------------------------------------
# derive_method_statuses (the put / get / havoc chips)
# ---------------------------------------------------------------------------


def test_derive_returns_idle_without_current_tick():
    assert derive_method_statuses("SUCCESS", {"5_0": "OK"}, None) == (
        "IDLE",
        "IDLE",
        "IDLE",
    )


def test_derive_handles_none_flag_avail():
    assert derive_method_statuses("OFFLINE", None, 7) == ("FAIL", "FAIL", "IDLE")


def test_derive_all_green():
    avail = {"5_0": "OK", "4_0": "OK", "3_0": "OK"}
    assert derive_method_statuses("SUCCESS", avail, 5) == ("OK", "OK", "OK")


def test_derive_putflag_missing_marks_put_fail_only():
    avail = {"5_0": "MISSING", "4_0": "OK", "3_0": "OK"}
    put, get, havoc = derive_method_statuses("MUMBLE", avail, 5)
    assert put == "FAIL"
    assert get == "OK"
    # PUT failed -> we can't tell whether HAVOC also failed.
    assert havoc == "IDLE"


def test_derive_getflag_missing_drives_recovering():
    avail = {"5_0": "OK", "4_0": "MISSING", "3_0": "OK"}
    put, get, havoc = derive_method_statuses("RECOVERING", avail, 5)
    assert put == "OK"
    assert get == "FAIL"
    # Overall RECOVERING -> HAVOC counts as OK.
    assert havoc == "OK"


def test_derive_havoc_only_failure():
    """PUT and GET both succeeded, but overall went MUMBLE -> HAVOC is the
    culprit."""
    avail = {"5_0": "OK", "4_0": "OK"}
    put, get, havoc = derive_method_statuses("MUMBLE", avail, 5)
    assert put == "OK"
    assert get == "OK"
    assert havoc == "FAIL"


def test_derive_first_tick_no_history():
    """At tick 1 the GETFLAG window is empty; GET should be IDLE, not FAIL."""
    avail = {"1_0": "OK"}
    put, get, havoc = derive_method_statuses("SUCCESS", avail, 1)
    assert put == "OK"
    assert get == "IDLE"
    assert havoc == "OK"


def test_derive_first_tick_hard_down():
    """At tick 1 with service hard-down, both PUT and GET should signal
    failure even though there's no GETFLAG history."""
    put, get, havoc = derive_method_statuses("OFFLINE", {}, 1)
    assert put == "FAIL"
    assert get == "FAIL"
    assert havoc == "IDLE"


def test_derive_multiple_payloads_all_ok():
    avail = {"5_0": "OK", "5_1": "OK", "4_0": "OK", "4_1": "OK"}
    assert derive_method_statuses("SUCCESS", avail, 5) == ("OK", "OK", "OK")


def test_derive_one_payload_missing_fails_group():
    avail = {"5_0": "OK", "5_1": "MISSING"}
    put, _, _ = derive_method_statuses("MUMBLE", avail, 5)
    assert put == "FAIL"


def test_derive_recovering_implies_havoc_ok_even_with_get_fail():
    avail = {"5_0": "OK", "3_0": "MISSING"}
    _, get, havoc = derive_method_statuses("RECOVERING", avail, 5)
    assert get == "FAIL"
    assert havoc == "OK"


def test_derive_unknown_overall_treated_as_offline():
    # An empty/garbage overall must not crash.
    put, get, havoc = derive_method_statuses("", {}, 3)
    assert (put, get, havoc) == ("FAIL", "FAIL", "IDLE")


def test_derive_tick_prefix_collision_resistance():
    """A flag from tick 50 must NOT be counted as a current-tick PUT result
    when current_tick is 5 (no string-prefix mismatch)."""
    avail = {"50_0": "OK"}  # NOT a 5_x key
    put, _, _ = derive_method_statuses("SUCCESS", avail, 5)
    # No 5_* entries -> IDLE (not OK, not FAIL).
    assert put == "IDLE"
