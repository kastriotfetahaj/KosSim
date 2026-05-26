import random
import re
from itertools import chain, permutations
from typing import Literal, assert_never

import pytest

from ctfroute.drivers.exceptions import BadState
from ctfroute.drivers.netfilter.driver import GateHandle, NetRefKind, NftablesDriver
from ctfroute.drivers.netfilter.nftables import Nftables
from ctfroute.state.external import NetRefKeyword, NetRefPrefix
from ctfroute.state.internal import ConnGate

# Two examples for each prefixed kind
PREFIX_EXAMPLES = set(chain(*((pf + "1", pf + "2") for pf in NetRefPrefix)))

BAD_COMBOS = {
    ("known", "same-team"),
    ("known", "other-team"),
    ("unknown", "same-team"),
    ("unknown", "other-team"),
    (None, "same-team"),
    ("same-team", None),
    ("same-team", "known"),
    ("same-team", "unknown"),
    ("same-team", "any-vulnbox"),
    ("same-team", "any-team"),
    ("same-team", "same-team"),
    ("same-team", "other-team"),
    ("same-team", "team-1"),
    ("same-team", "vulnbox-1"),
    ("same-team", "game-1"),
    (None, "other-team"),
    ("other-team", None),
    ("other-team", "known"),
    ("other-team", "unknown"),
    ("other-team", "same-team"),
    ("other-team", "other-team"),
    ("other-team", "game-1"),
    ("game-1", "same-team"),
    ("game-1", "other-team"),
}


@pytest.mark.parametrize("src,dst", BAD_COMBOS)
def test_bad_gates(src, dst):
    with pytest.raises(BadState):
        NftablesDriver._render_conn_gate(
            ConnGate(id="test", conn_src=src, conn_dst=dst)
        )


ALL_EXAMPLE_VALUES = set(str(x) for x in NetRefKeyword) | PREFIX_EXAMPLES | {None}

# All possible combinations of src and dst (two examples for team-, vulnbox- and game-)
ALL_COMBOS = set(permutations(ALL_EXAMPLE_VALUES, 2))

# The ones that should not raise exceptions when set
GOOD_COMBOS = (
    ALL_COMBOS
    - BAD_COMBOS
    # In the test_bad_gates we don't test with multiple examples for teams etc. so we
    # remove those from ALL_COMBOS here.
    - {
        ("same-team", "team-2"),
        ("same-team", "vulnbox-2"),
        ("same-team", "game-2"),
        ("other-team", "game-2"),
        ("game-2", "same-team"),
        ("game-2", "other-team"),
    }
)


@pytest.mark.parametrize("src,dst", GOOD_COMBOS)
def test_no_exceptions_rendering(src, dst):
    """Check that all the other "good" combinations render without exceptions."""
    NftablesDriver._render_conn_gate(ConnGate(id="test", conn_src=src, conn_dst=dst))


@pytest.fixture
def driver(ready_gatekeeper):
    return ready_gatekeeper.driver


def replace_endpoint_randomly(gate: ConnGate, which: Literal["src"] | Literal["dst"]):
    if which == "src":
        src_cands = tuple(
            s for s, d in GOOD_COMBOS if d == gate.conn_dst and s != gate.conn_src
        )
        gate.conn_src = random.choice(src_cands)
    elif which == "dst":
        dst_cands = tuple(
            d for s, d in GOOD_COMBOS if s == gate.conn_src and d != gate.conn_dst
        )
        gate.conn_dst = random.choice(dst_cands)


@pytest.mark.parametrize("src,dst", GOOD_COMBOS)
def test_no_invalid_nft(src, dst, driver, seed, rand_ent_id):
    """Assert that the nft rendered by the driver is at least syntactically valid."""
    gate = ConnGate(id=rand_ent_id, conn_src=src, conn_dst=dst)

    # Can be created ...
    handles = driver.set_gate(gate)

    # Can be updated
    replace_endpoint_randomly(gate, "src")
    handles = driver.set_gate(gate, handles)

    # Can be updated again
    replace_endpoint_randomly(gate, "dst")
    handles = driver.set_gate(gate, handles)

    # And again with an expr
    gate.expression = "tcp dport 22"
    handles = driver.set_gate(gate, handles)

    # ... and removed
    driver.delete_gate(handles)


def expexted_rule_keywords(gate: ConnGate) -> set[str]:
    """
    Here we derive some keywords we would expect in the rule for a gate.

    This is used for shitty unit tests that substitute integration tests until we have
    an http server and adapter.
    """
    keywords: set[str] = set()
    for endpoint in (gate.conn_src, gate.conn_dst):
        kind = NftablesDriver._get_net_ref_kind(endpoint) if endpoint else None
        match kind:
            case None:
                ...
            case NetRefKeyword.same_team:
                ...  # Depends on the other endpoint...
            case NetRefKeyword.other_team:
                # Always requires this check
                keywords.add(f"!= @{NetRefKeyword.same_team}")
            case NetRefKeyword.any_team | NetRefKeyword.any_vulnbox:
                keywords.add(f"@{kind}")
            case NetRefPrefix.team | NetRefPrefix.vulnbox:
                # teams and vulnboxes are both targeted with @t-
                keywords.add("addr @t-")
            case NetRefPrefix.vulnbox:
                # vulnboxes additionally need to be in any-vulnbox
                keywords.add(f"addr @{NetRefKeyword.any_vulnbox}")
            case NetRefPrefix.game:
                keywords.add("addr @g-")
            case NetRefPrefix.team:
                keywords.add("addr @t-")
            case NetRefKeyword.unknown:
                keywords.add("addr != @known")
            case NetRefKeyword.known:
                keywords.add("addr @known")
            case _:
                assert_never(NetRefKind | None)

    return keywords


def assert_keywords(nft: Nftables, gate: ConnGate, handle: GateHandle):
    """
    Assert that certain keywords are contained in the rules for a gate.

    This is used for shitty unit tests that substitute integration tests until we have
    an http server and adapter.
    """
    rule = get_raw_rule(nft, handle)
    assert rule is not None
    for word in expexted_rule_keywords(gate):
        assert word in rule


def get_raw_rule(nft: Nftables, handle: GateHandle) -> str:
    """
    Get the string representation of a Gate by its GateHandle.

    This is used for shitty unit tests that substitute integration tests until we have
    an http server and adapter.
    """
    nft.set_handle_output(True)
    code, out, err = nft.cmd(
        f"list chain {NftablesDriver.TABLE} {NftablesDriver.CHAIN}"
    )
    nft.set_handle_output(False)
    assert code == 0
    rule = None
    for line in out.splitlines():
        if f"handle {tuple(handle)[0]}" in line:
            assert rule is None
            rule = line.lstrip()

    assert rule is not None
    # We add comments into rules for easier intervention, but this might lead to
    #  false positives in the keyword checks, so I am stripping the comment here
    rule = re.sub(r'comment "[^"]+"', "", rule)
    return rule


@pytest.mark.parametrize("src,dst", GOOD_COMBOS)
def test_keywords_nft(src, dst, driver, seed, rand_ent_id, nft):
    gate = ConnGate(id="good", conn_src=src, conn_dst=dst)
    handle = driver.set_gate(gate)
    assert_keywords(nft, gate, handle)
    driver.delete_gate(handle)
