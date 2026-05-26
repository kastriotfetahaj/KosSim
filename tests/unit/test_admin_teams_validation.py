"""Pydantic-validation tests for the admin team CRUD bodies.

These exercise the constraint patterns without touching the DB. We import
the Pydantic models directly from the admin_api module.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ksapp.admin_api import TeamCreateBody, TeamUpdateBody


# ---------------------------------------------------------------------------
# TeamCreateBody
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["team1", "Team_2", "a", "x-y-z", "T1-team"])
def test_create_accepts_well_formed_names(name):
    body = TeamCreateBody(name=name)
    assert body.name == name
    assert body.country_code == "XK"  # default
    assert body.is_nop is False


@pytest.mark.parametrize(
    "name",
    [
        "",
        "_underscoreStart",
        "-dashStart",
        "has space",
        "has.dot",
        "has/slash",
        "x" * 64,  # > 63 chars
    ],
)
def test_create_rejects_malformed_names(name):
    with pytest.raises(ValidationError):
        TeamCreateBody(name=name)


@pytest.mark.parametrize("cc", ["XK", "IT", "us", "Gb"])
def test_create_accepts_two_letter_country_codes(cc):
    body = TeamCreateBody(name="t", country_code=cc)
    # The endpoint upper()s the code before storage, but the model itself
    # only checks the regex (which is case-insensitive).
    assert body.country_code.lower() == cc.lower()


@pytest.mark.parametrize("cc", ["X", "XKK", "12", "X1", ""])
def test_create_rejects_bad_country_codes(cc):
    with pytest.raises(ValidationError):
        TeamCreateBody(name="t", country_code=cc)


def test_create_optional_fields_default_to_none():
    body = TeamCreateBody(name="t")
    assert body.nat_alias is None
    assert body.submit_token is None
    assert body.is_nop is False


# ---------------------------------------------------------------------------
# TeamUpdateBody
# ---------------------------------------------------------------------------


def test_update_accepts_partial():
    body = TeamUpdateBody(country_code="IT")
    assert body.country_code == "IT"
    assert body.name is None
    assert body.is_nop is None


def test_update_all_none_is_valid_pydantic_object():
    """The validator allows an all-None body; the API endpoint rejects it
    separately ("no fields to update")."""
    body = TeamUpdateBody()
    assert body.name is None and body.country_code is None


def test_update_invalid_country_rejected():
    with pytest.raises(ValidationError):
        TeamUpdateBody(country_code="XYZ")


def test_update_invalid_name_rejected():
    with pytest.raises(ValidationError):
        TeamUpdateBody(name="bad name with spaces")
