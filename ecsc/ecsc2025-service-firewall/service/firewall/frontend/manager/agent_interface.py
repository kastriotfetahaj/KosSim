import asyncio
from io import BytesIO
from time import time
import os
import tempfile

from pysnmp.entity.engine import SnmpEngine
from pysnmp.hlapi.transport import AbstractTransportTarget
from pysnmp.hlapi.v1arch.asyncio import CommunityData, SnmpDispatcher, UdpTransportTarget, get_cmd, next_cmd, set_cmd
from pysnmp.smi import builder, compiler, view, error
from pysnmp.proto import api, rfc1902, rfc1905

from .exception import SNMPException

mib_view = None
monitoring_oid = None
user_monitoring_oid = None
custom_oid = None
default_community = None
auth_community = None


class RawSnmpDispatcher(SnmpDispatcher):
    """
    Extension to the SnmpDispatcher that allows sending raw data instead of PDUs
    """

    def send_pdu(
        self,
        transportTarget: AbstractTransportTarget,
        outgoingMsg: bytes,
        cbFun=None,
        cbCtx=None,
    ):
        if self._automaticDispatcher and transportTarget.TRANSPORT_DOMAIN not in self._configuredTransports:
            self.transport_dispatcher.register_transport(
                transportTarget.TRANSPORT_DOMAIN,
                transportTarget.PROTO_TRANSPORT().open_client_mode(transportTarget.iface),
            )
            self._configuredTransports.add(transportTarget.TRANSPORT_DOMAIN)

        self._pendingReqs[0] = dict(
            outgoingMsg=outgoingMsg,
            transportTarget=transportTarget,
            cbFun=cbFun,
            cbCtx=cbCtx,
            timestamp=time() + transportTarget.timeout,
            retries=0,
            raw=True,
        )

        self.transport_dispatcher.send_message(
            outgoingMsg,
            transportTarget.TRANSPORT_DOMAIN,
            transportTarget.transport_address,
        )

        self.transport_dispatcher.job_started(id(self))

    def _recv_callback(self, snmpEngine: SnmpEngine, transportDomain, transportAddress, wholeMsg):
        try:
            stateInfo = self._pendingReqs.pop(0)
        except KeyError:
            return wholeMsg

        self.transport_dispatcher.job_finished(id(self))

        cbFun = stateInfo["cbFun"]
        cbCtx = stateInfo["cbCtx"]

        if cbFun:
            cbFun(self, 0, None, wholeMsg, cbCtx)


async def raw_cmd(
    snmpDispatcher: SnmpDispatcher, transportTarget: AbstractTransportTarget, outgoingMsg: bytes
) -> "tuple[errind.ErrorIndication | None, bytes]":

    def __callback(snmpDispatcher, stateHandle, errorIndication, wholeMsg, future):
        if future.cancelled():
            return
        future.set_result((errorIndication, wholeMsg))

    future = asyncio.Future()

    snmpDispatcher.send_pdu(transportTarget, outgoingMsg, cbFun=__callback, cbCtx=future)

    return await future


def parse_message_header(stream: BytesIO) -> (int, int):
    tag = stream.read(1)
    if len(tag) != 1:
        raise SNMPException("Invalid data", 400)
    length = stream.read(1)
    if len(length) != 1:
        raise SNMPException("Invalid data", 400)
    return tag[0], length[0]


def parse_message_value(stream: BytesIO) -> (int, bytes):
    tag, length = parse_message_header(stream)
    data = stream.read(length)
    if len(data) != length:
        raise SNMPException("Invalid data", 400)
    return tag, data


def parse_pdu(pdu: bytes) -> (int, bytes, int):
    stream = BytesIO(pdu)
    tag, length = parse_message_header(stream)
    if length > len(pdu):
        raise SNMPException("Invalid data", 400)
    tag, data = parse_message_value(stream)
    version = int.from_bytes(data, byteorder="big")
    if version != 1:
        raise SNMPException("Invalid Version", 400)
    tag, data = parse_message_value(stream)
    community = data
    tag, length = parse_message_header(stream)
    pdu_type = tag
    # for now we parse only until here as we don't need the remaining data
    return version, community, pdu_type


def load_mib():
    global mib_view
    mibBuilder = builder.MibBuilder()
    compiler.add_mib_compiler(mibBuilder, sources=["/usr/share/mib/"], destination=tempfile.mkdtemp(prefix='compiled-mib'))
    mibBuilder.load_modules("ECSC2025-ATKLAB-FIREWALL-MIB")
    mib_view = view.MibViewController(mibBuilder)


def mib_get_oid(label: str) -> tuple[int]:
    assert mib_view is not None
    oid, label, suffix = mib_view.get_node_name((label,))
    return oid


def mib_get_label(oid: tuple[int]) -> str:
    assert mib_view is not None
    oid, label, suffix = mib_view.get_node_name(oid)
    return label


def string_to_oid(s: str) -> tuple[int]:
    oid = []
    for c in s:
        oid.append(ord(c))
    return tuple(oid)


def bytes_to_oid(s: bytes) -> tuple[int]:
    oid = []
    for c in s:
        oid.append(c)
    return tuple(oid)


def init(default_community_str: str, auth_community_str: str):
    global monitoring_oid, user_monitoring_oid, custom_oid, default_community, auth_community
    load_mib()
    monitoring_oid = mib_get_oid("monitoring")
    user_monitoring_oid = mib_get_oid("userMonitoringEntry")
    custom_oid = mib_get_oid("customValue")
    default_community = CommunityData(default_community_str)
    auth_community = CommunityData(auth_community_str)


async def snmp_raw(msg: bytes, timeout=5) -> bytes:
    # TODO: The SnmpDispatcher object may be expensive to create, therefore it is advised to maintain it for the lifecycle of the application/thread for as long as possible.
    snmpDispatcher = RawSnmpDispatcher()
    try:
        transport = await UdpTransportTarget.create(("127.0.0.1", 1161), timeout=1, retries=3)

        # wrap the cmd_fn in another wait because the internal timeout implementation is broken
        try:
            iterator = await asyncio.wait_for(raw_cmd(snmpDispatcher, transport, msg), timeout=5)
        except TimeoutError:
            raise SNMPException("Timeout during upstream request", 500)
        error_indication, response = iterator

        if error_indication:
            # only used for timout error
            raise SNMPException(f"error indication: {error_indication}", 500)
        return response
    finally:
        snmpDispatcher.transport_dispatcher.close_dispatcher()


async def snmp_cmd(oid: tuple[int], cmd_fn, community, value=None, timeout=5):
    # TODO: The SnmpDispatcher object may be expensive to create, therefore it is advised to maintain it for the lifecycle of the application/thread for as long as possible.
    snmpDispatcher = SnmpDispatcher()
    try:
        transport = await UdpTransportTarget.create(("127.0.0.1", 1161), timeout=1, retries=3)

        # wrap the cmd_fn in another wait because the internal timeout implementation is broken
        try:
            iterator = await asyncio.wait_for(cmd_fn(snmpDispatcher, community, transport, (oid, value)), timeout=5)
        except TimeoutError:
            raise SNMPException("Timeout during upstream request", 500)
        error_indication, error_status, error_index, var_binds = iterator

        if error_indication:
            # only used for timout error
            raise SNMPException(f"error indication: {error_indication}", 500)
        elif error_status:
            raise SNMPException(f"SNMP error: {error_status}", 500)

        if len(var_binds) != 1:
            raise SNMPException("Invalid variable bindings", 500)
        var_bind = var_binds[0]
        if len(var_bind) != 2:
            raise SNMPException("Invalid variable binding", 500)
        return var_bind
    finally:
        snmpDispatcher.transport_dispatcher.close_dispatcher()


async def snmp_get_next(oid: tuple[int], timeout=5):
    assert default_community is not None
    name, value = await snmp_cmd(oid, next_cmd, default_community, None, timeout)
    if isinstance(value, rfc1905.NoSuchObject):
        return None
    return name, value


async def snmp_get(oid: tuple[int], timeout=5):
    assert default_community is not None
    name, value = await snmp_cmd(oid, get_cmd, default_community, None, timeout)
    if name != oid:
        raise SNMPException("Query returned wrong name", 500)
    if isinstance(value, rfc1905.NoSuchObject):
        return None
    return value


async def snmp_set(oid: tuple[int], value: str, timeout=5):
    assert auth_community is not None
    name, value = await snmp_cmd(oid, set_cmd, auth_community, value, timeout)
    if name != oid:
        raise SNMPException("Query returned wrong name", 500)
    if isinstance(value, rfc1905.NoSuchObject):
        return None
    return value


def get_raw(msg: bytes) -> bytes:
    version, community, pdu_type = parse_pdu(msg)
    if pdu_type != 0xA0:
        raise SNMPException(f"PDU type {pdu_type:#x} is not allowed", 403)
    value = asyncio.run(snmp_raw(msg))
    return value


def get_custom_value(identifier: bytes, secret: bytes) -> bytes:
    assert custom_oid is not None
    oid = custom_oid + bytes_to_oid(identifier) + bytes_to_oid(secret)
    value = asyncio.run(snmp_get(oid))
    if value is None:
        raise SNMPException("Query returned no object", 404)
    if isinstance(value, rfc1905.NoSuchInstance):
        raise SNMPException("This custom value could not be found", 404)
    if not isinstance(value, rfc1902.OctetString):
        raise SNMPException("Query returned invalid type", 500)
    value = value.asOctets()
    return value


def set_custom_value(identifier: bytes, secret: bytes, value: bytes) -> bytes:
    assert custom_oid is not None
    oid = custom_oid + bytes_to_oid(identifier) + bytes_to_oid(secret)
    value = rfc1902.OctetString(value)
    value = asyncio.run(snmp_set(oid, value))
    if value is None:
        raise SNMPException("No custom value found", 404)
    if not isinstance(value, rfc1902.OctetString):
        raise SNMPException("Query returned invalid type", 500)
    value = value.asOctets()
    return value


def get_monitoring_value(label: str) -> str:
    try:
        oid = mib_get_oid(label)
    except error.NoSuchObjectError:
        raise SNMPException("Label doesn't exists", 400)
    value = asyncio.run(snmp_get(oid))
    if value is None:
        raise SNMPException("No monitoring value found", 404)
    if not isinstance(value, rfc1902.Counter64):
        raise SNMPException("Query returned invalid type", 500)
    return str(int(value))


def get_user_monitoring_value(identifier: bytes, label: str) -> bytes | int | None:
    try:
        oid = mib_get_oid(label)
    except error.NoSuchObjectError:
        raise SNMPException("Label doesn't exists", 400)
    value = asyncio.run(snmp_get(oid + bytes_to_oid(identifier)))
    if value is None:
        raise SNMPException("No monitoring value found", 404)
    if value.isSameTypeWith(rfc1902.Null):
        return None
    if isinstance(value, rfc1902.Integer32):
        return int(value)
    if isinstance(value, rfc1902.OctetString):
        return bytes(value).hex()
    raise SNMPException("Query returned invalid type", 500)


async def get_monitoring_values_walk() -> list[tuple[rfc1902.ObjectName, int]]:
    assert monitoring_oid is not None
    values = []
    name = monitoring_oid
    while True:
        res = await snmp_get_next(name)
        if res is None:
            break
        name, value = res
        if isinstance(value, rfc1905.EndOfMibView):
            break
        if name[:-1] != monitoring_oid:
            break
        values.append((name, int(value)))
    return values


def get_monitoring_values() -> dict[str, str]:
    values = asyncio.run(get_monitoring_values_walk())
    new_values = {}
    for name, value in values:
        label = mib_get_label(name)[-1]
        new_values[label] = str(value)
    return new_values

def get_user_monitoring_labels() -> list[str]:
    assert user_monitoring_oid is not None
    labels = []
    for i in range(100):
        label = mib_get_label(user_monitoring_oid + (i,))[-1]
        if label == "userMonitoringEnd":
            break
        labels.append(label)
    return labels
