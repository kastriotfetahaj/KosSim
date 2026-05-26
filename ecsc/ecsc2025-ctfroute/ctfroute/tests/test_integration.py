import tempfile
from itertools import permutations
from random import Random

import pytest
import scapy.utils
from scapy.all import IP, TCP

from ctfroute.adapters.yaml_conf import YamlConfig
from ctftest.agent.ctftest_pb2 import (
    ListenStatus,
    SniffRecordingResponse,
    SniffStatus,
    StopSniffResponse,
)


@pytest.mark.parametrize("src,tgt", permutations(range(1, 5), 2))
@pytest.mark.asyncio
@pytest.mark.integration
async def test_ping_between_boxes(integration_ctfroute_client, src, tgt):
    async with integration_ctfroute_client as client:
        result = await client.vulnbox_ping(src, tgt)
        assert result.success


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("echo", (False, True))
@pytest.mark.parametrize("src,tgt", permutations(range(1, 5), 2))
async def test_nat(
    src: int,
    tgt: int,
    integration_ctfroute_client,
    echo: bool,
    integration_ctfroute_conf: YamlConfig,
    random: Random,
):
    gateway_ip: str = str(
        integration_ctfroute_conf.initial_state.teamsById[str(tgt)].gateway
    )
    vulnbox_ip: str = str(
        integration_ctfroute_conf.initial_state.teamsById[str(tgt)].vulnbox
    )
    port = 2000
    sniffer_updates = integration_ctfroute_client.start_sniff(
        box=tgt, filter=f"tcp and port {port}", seconds=300
    )
    # wait for sniffer to run before we continue
    sniffer_updates = await sniffer_updates
    assert sniffer_updates.uuid

    recv_updates = integration_ctfroute_client.vulnbox_tcp_recv(
        tgt, port, amount=1024, echo=echo, collect=True
    )
    ready_msg = await anext(recv_updates)
    assert ready_msg.status == ListenStatus.READY

    message = random.randbytes(1024)

    send_result = await integration_ctfroute_client.vulnbox_tcp_send(
        src, tgt, port, message, echo_recv=echo, echo_collect=True
    )

    done_msg = await anext(recv_updates)
    assert message == done_msg.message
    if echo:
        assert message == send_result.response

    sniffer_result: StopSniffResponse = await integration_ctfroute_client.stop_sniff(
        box=tgt, uuid=sniffer_updates.uuid
    )
    assert sniffer_result.status == SniffStatus.STOPPED_MANUALLY

    sniffer_recording: SniffRecordingResponse = (
        await integration_ctfroute_client.get_sniff_recording(
            box=tgt, uuid=sniffer_updates.uuid
        )
    )

    with tempfile.NamedTemporaryFile(delete_on_close=False) as f:
        f.write(sniffer_recording.recording)
        f.close()

        sniffer = scapy.utils.PcapNgReader(f.name)
        ips = set()
        for packet in sniffer:
            if packet.haslayer(IP):
                ips.add(packet.src)
                ips.add(packet.dst)
                if packet.src != vulnbox_ip:
                    assert packet.ttl <= 48
                    if packet.haslayer(TCP):
                        # We NOP all tcp options except MSS
                        tcp_packet = packet[TCP]
                        options = {opt for opt, _ in tcp_packet.options}
                        assert options <= {"NOP", "MSS"}

        assert ips == {
            vulnbox_ip,
            gateway_ip,
        }  # will fail if NAT does not anonymize traffic

    assert done_msg.status == ListenStatus.DONE

    assert done_msg.duration < 15.0
    assert send_result is not None
    assert send_result.duration < 15.0
