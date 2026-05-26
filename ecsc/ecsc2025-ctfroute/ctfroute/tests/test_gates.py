from asyncio import sleep
from itertools import permutations
from random import Random

import pytest
from ctfroute_k8s.models.v1 import Gate
from ctfroute_k8s.utils.async_helper import add_connection_gate

from ctftest.agent.client import VulnboxesClient
from ctftest.agent.ctftest_pb2 import ListenStatus

GATE_ENFORCEMENT_SLA = 0.5


async def tcp_send_roundtrip(
    client: VulnboxesClient, random: Random, src: int, dst: int, port: int = 2000
) -> bool:
    receiver = client.vulnbox_tcp_recv(dst, port, echo=True, collect=True, amount=1024)

    recv_result = await anext(receiver)
    assert recv_result.status == ListenStatus.READY

    message = random.randbytes(1024)

    send_result = await client.vulnbox_tcp_send(
        src, dst, port=port, message=message, echo_recv=True, echo_collect=True
    )

    recv_result = await anext(receiver)
    assert recv_result.status == ListenStatus.DONE

    return (
        send_result.success
        and message == recv_result.message
        and message == send_result.response
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.kubernetes
@pytest.mark.parametrize("block_pre", [True, False])
@pytest.mark.parametrize("src,dst", permutations(range(1, 5), 2))
async def test_gates_simple(
    k8s_namespace,
    k8s_ctfroute_client: VulnboxesClient,
    random,
    src: int,
    dst: int,
    block_pre: bool,
):
    """Test smple connection gates between teams."""
    await Gate.async_delete_all(namespace=k8s_namespace)
    block_post = not block_pre

    if block_pre:
        await add_connection_gate(
            namespace=k8s_namespace,
            name="pre-gate",
            conn_src=f"team-{src}",
            conn_dst=f"team-{dst}",
            expression="",
        )
        await sleep(GATE_ENFORCEMENT_SLA)
    success = await tcp_send_roundtrip(k8s_ctfroute_client, random, src, dst)
    assert success != block_pre

    if block_pre:
        Gate.delete(namespace=k8s_namespace, name="pre-gate")
        await sleep(GATE_ENFORCEMENT_SLA)

    if block_post:
        await add_connection_gate(
            namespace=k8s_namespace,
            name="post-gate",
            conn_src=f"team-{src}",
            conn_dst=f"team-{dst}",
            expression="",
        )
        await sleep(GATE_ENFORCEMENT_SLA)
    success = await tcp_send_roundtrip(k8s_ctfroute_client, random, src, dst)
    assert success != block_post


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.kubernetes
@pytest.mark.parametrize("src,dst", [(1, 2), (3, 4)])
async def test_gates_directional(
    k8s_namespace,
    k8s_ctfroute_client: VulnboxesClient,
    random,
    src: int,
    dst: int,
):
    await Gate.async_delete_all(namespace=k8s_namespace)
    """Conngates only affect the described direction, not the inverese."""
    await add_connection_gate(
        namespace=k8s_namespace,
        name="gate",
        conn_src=f"team-{src}",
        conn_dst="other-team",
        expression="",
    )
    await sleep(GATE_ENFORCEMENT_SLA)
    status = await tcp_send_roundtrip(k8s_ctfroute_client, random, src, dst)
    assert status is False
    status = await tcp_send_roundtrip(k8s_ctfroute_client, random, dst, src)
    assert status is True


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.kubernetes
@pytest.mark.parametrize("src,dst", [(1, 2), (3, 4)])
async def test_gates_dst_port(
    k8s_namespace,
    k8s_ctfroute_client: VulnboxesClient,
    random,
    src: int,
    dst: int,
    block_port: int = 1337,
):
    """Expression correctly filters specific port."""
    await Gate.async_delete_all(namespace=k8s_namespace)
    await add_connection_gate(
        namespace=k8s_namespace,
        name="gate",
        conn_src="other-team",
        conn_dst="any-vulnbox",
        expression=f"tcp dport {block_port}",
    )
    await sleep(GATE_ENFORCEMENT_SLA)
    status = await tcp_send_roundtrip(
        k8s_ctfroute_client, random, src, dst, port=block_port
    )
    assert status is False
    status = await tcp_send_roundtrip(
        k8s_ctfroute_client, random, src, dst, port=block_port + 1
    )
    assert status is True


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.kubernetes
@pytest.mark.parametrize(
    "src,dst",
    [
        (1, 2),
        (3, 4),  # these teams use the same router
    ],
)
async def test_gates_same_team(
    k8s_namespace,
    k8s_ctfroute_client: VulnboxesClient,
    random,
    src: int,
    dst: int,
):
    """Gates also work with teams on the same router."""
    await Gate.async_delete_all(namespace=k8s_namespace)
    await add_connection_gate(
        namespace=k8s_namespace,
        name="gate",
        conn_src="any-team",
        conn_dst="same-team",
        expression="",
    )
    await sleep(GATE_ENFORCEMENT_SLA)
    success = await tcp_send_roundtrip(k8s_ctfroute_client, random, src, dst)
    assert success


# TODO: testing same-team blocked needs one more client running ctftest-agent
# TODO: Test gates with periods
