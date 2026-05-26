import logging

import pytest
from tests.test_gate_rendering import BAD_COMBOS, GOOD_COMBOS, replace_endpoint_randomly

from ctfroute.controllers import GateKeeper
from ctfroute.drivers.netfilter.driver import GateHandle
from ctfroute.state.internal import ConnGate
from ctfroute.utils import EntityType


def test_bad_nft(caplog, ready_gatekeeper):
    """Gatekeeper shall not fail if the passed network.nft is invalid."""
    gk = ready_gatekeeper
    gk.state.network.nft = "bad"
    gk.gates_to_retry = set()
    with caplog.at_level(logging.ERROR, logger="ctfroute"):
        gk._setup()

    assert "syntax error" in caplog.text


@pytest.fixture
def reset_gatekeeper(ready_gatekeeper, gates_initial_state) -> GateKeeper:
    gk = ready_gatekeeper

    gk.state.gates = [g.model_copy(deep=True) for g in gates_initial_state.gates]
    gk.gates_to_retry = set()

    # flushes chains and handles
    gk._setup()

    # Drain updates queue
    while not gk.updates.empty():
        gk.updates.get_nowait()

    return gk


@pytest.mark.asyncio
@pytest.mark.parametrize("src,dst", BAD_COMBOS)
async def test_bad_gates(reset_gatekeeper, src, dst):
    """Assert that gatekeeper adequately handles bad gates."""
    gk = reset_gatekeeper

    gate = ConnGate(id="bad", conn_src=src, conn_dst=dst)
    await gk.gate_update(gate.model_copy(deep=True))
    update = await gk.updates.get()
    assert update.entity_id == "bad"
    assert update.entity_type == EntityType.Gate
    assert gk.KEYS.ERROR_MESSAGE in update.update
    assert gk.KEYS.ENFORCED in update.update
    assert update.update[gk.KEYS.ENFORCED] == "False"

    # This is not bad nft but bad state, there should be no error code
    assert gk.KEYS.ERROR_CODE not in update.update

    # Bad gates will not be reattempted
    assert not gk.gates_to_retry


async def assert_gate_set(gk, gate) -> GateHandle:
    """Set a gate and assert success criteria."""
    await gk.gate_update(gate.model_copy(deep=True))
    update = await gk.updates.get()
    assert update.entity_id == gate.id
    assert update.entity_type == EntityType.Gate
    assert update.update[gk.KEYS.ENFORCED] == "True"
    assert gate.id not in gk.gates_to_retry
    assert gate.id in gk.gate_handles
    return gk.gate_handles[gate.id]


@pytest.mark.asyncio
@pytest.mark.parametrize("src,dst", GOOD_COMBOS)
async def test_good_gates(reset_gatekeeper, src, dst, nft):
    """Assert that gatekeeper adequately handles good gates."""
    gk = reset_gatekeeper
    prexisting_handles = len(gk.gate_handles)

    gate = ConnGate(id="good", conn_src=src, conn_dst=dst)
    await assert_gate_set(gk, gate)
    assert len(gk.gate_handles) == prexisting_handles + 1

    # Modify src
    replace_endpoint_randomly(gate, "src")
    await assert_gate_set(gk, gate)
    assert len(gk.gate_handles) == prexisting_handles + 1

    # Modify dst
    replace_endpoint_randomly(gate, "dst")
    await assert_gate_set(gk, gate)
    assert len(gk.gate_handles) == prexisting_handles + 1

    # Delete the gate
    await gk.gate_update(gate.model_copy(deep=True), delete=True)
    assert gate.id not in gk.gate_handles
    assert len(gk.gate_handles) == prexisting_handles
    assert gate.id not in gk.gates_to_retry

    # Create it again
    await assert_gate_set(gk, gate)
    assert len(gk.gate_handles) == prexisting_handles + 1

    # Delete it
    await gk.gate_update(gate.model_copy(deep=True), delete=True)
    assert gate.id not in gk.gate_handles
    assert len(gk.gate_handles) == prexisting_handles
    assert gate.id not in gk.gates_to_retry


@pytest.mark.asyncio
async def test_gate_nochange(reset_gatekeeper, nft):
    gk = reset_gatekeeper

    gate = ConnGate(id="good", conn_src="team-1", conn_dst=None)
    await assert_gate_set(gk, gate.model_copy(deep=True))
    await gk.gate_update(gate.model_copy(deep=True))

    # The gate didn't change, there mustn't be any update!
    assert gk.updates.empty()
