import asyncio

from Crypto.Cipher import AES

from heavensent_lib import *

PORT_WINDOW = 10
BASE_PORT = 10000
PORT_POOL = None


def get_port_pool():
    global PORT_POOL
    if PORT_POOL is None:
        PORT_POOL = asyncio.Queue()
        for x in range(PORT_WINDOW):
            PORT_POOL.put_nowait(BASE_PORT + x)
        # print("Port pool initialized")
    return PORT_POOL


BANNER = """        *                                           .      +
                        *      +    |  |                      |
  + '                      |       -o--o-*        .-.       - o -
'          '            o--o--      |  |         ( (    + *   |
              '    '       |       *  .:'         `-'     o *         ~~+
.           ' .    _____                                 _         +~~ .
.       .         |  |  |___ ___ _ _ ___ ___ ___ ___ ___| |_     ':.
                + |     | -_| .'| | | -_|   |_ -| -_|   |  _|      '::._  '
       .          |__|__|___|__,|\\_/|___|_|_|___|___|_|_|_|          '._)
           ' +~~            .   +        .        ++~~   .
    +      .   o  '   .   *                          .:'       .         +'
      '     .          _|_   o         |         _.::'      |
   o .   '     |   . .  |   .   |  o - o -   | .(_.'  +  '- o -               o
 .      '    .-+-         + *  -o-     |   - o -            |         *    .
    '          |            '   |            |          *               '  o"""


BROADCAST_MESSAGE_SIZE = 32
EXPERIMENT_TAG_CHUNK_SIZE = 32
DOWNLINK_CHUNK_SIZE = 32


class Info:
    def __init__(self):
        self.gs_id = None
        self.password = None

    def gs_is_registered(self):
        return self.gs_id is not None and self.password is not None


INFO = Info()
EXPLANATION = """This program is a ground station, which communicates with a satellite.
The satellite has two main functionalities:
1. Passing of broadcast messages
2. Creating of science experiments

The satellite is a multi-user system, meaning multiple ground stations can
communicate with, and use the satellite.
Since one operator of the satellite can have multiple ground stations, the
ground station are grouped into operator networks.
Each ground station in the same operator network can access all broadcast
messages of the other ground stations, enabling message sharing.

The satellite also has a science payload on board, which may be operated by a
ground station.
The results of such an experiment can be downloaded from the satellite.
In case the downlink budget is not enough for one ground station, another
ground station with more link budget can download the encrypted result of the
experiment and send it to the asking ground station by terrestrial channels.
The asking ground station can then ask the satellite for the decryption key
of the encrypted experiment result.

Communication with the satellite happens by radio. This is emulated through a
TCP link transporting complex float32 I/Q data at 48000 samples per second.
Over this link, a custom RF protocol is implemented.
"""

HELP = [
    "switch_ground <gs_id:x> <password:x>",
    "reg_ground_station",
    "reg_operator [operator_id:x operator_secret:x]",
    "send_broadcast <slot> <message>",
    "recv_broadcast <slot> [other_gs_id:x]",
    "run_experiment [message]",
    "downlink <experiment_id:x> [other_gs_id:x]",
    "decrypt_downlink <experiment_id:x> <data:x>"
]


def change_ground_station(*args):
    global INFO

    if len(args) < 2:
        print(HELP[0])
        return

    gs_id = args[0]
    password = args[1]

    try:
        INFO.gs_id = int(gs_id, 16)
    except ValueError:
        print("[-] The ground station id has to be a hex number")
        return

    if password.startswith("0x"):
        password = password[2:]
    try:
        INFO.password = int(password, 16)
    except ValueError:
        print("[-] The password has to be a hex number")
        return

    print("[+] Changed ground station")


async def register_ground_station(conn: Connection, *_):
    global INFO

    gs_reg = RegisterGroundStation()
    gs_reg_ret = RegisterGroundStationResponse(
        await conn.send(gs_reg.prepare_message()))

    if gs_reg_ret.error != ErrorCode.Success:
        print(f"[-] Could not register ground station: {gs_reg_ret}")
        return

    INFO.password = gs_reg.password
    INFO.gs_id = gs_reg_ret.gs_id

    print(
        f"[+] G/S registered successfully with {INFO.gs_id:x}:{INFO.password:x}")


async def register_gs_at_op(conn: Connection, *args):
    global INFO

    if len(args) >= 2:
        op_id = args[0]
        op_secret = args[1]

        if op_id.startswith("0x"):
            op_id = op_id[2:]
        try:
            op_id = int(op_id, 16)
        except ValueError:
            print("[-] The operator id has to be a hex number")
            return

        if op_secret.startswith("0x"):
            op_secret = op_secret[2:]
        try:
            op_secret = int(op_secret, 16)
        except ValueError:
            print("[-] The operator network secret has to be a hex number")
            return

        gs_op_reg = RegisterAtOperator(
            INFO.gs_id, INFO.password, op_id, op_secret)
        gs_op_reg_ret = RegisterAtOperatorResponse(await conn.send(gs_op_reg.prepare_message()))

        if gs_op_reg_ret.error != ErrorCode.Success:
            print(
                f"[-] Could not register ground station at operator: {gs_op_reg_ret}")
            return

    else:
        op_reg = RegisterOperator(INFO.gs_id, INFO.password)
        op_reg_ret = RegisterOperatorResponse(
            await conn.send(op_reg.prepare_message()))

        if op_reg_ret.error != ErrorCode.Success:
            print(f"[-] Could not register new operator: {op_reg_ret}")
            return

        op_id = op_reg_ret.op_id
        op_secret = op_reg_ret.op_secret

    print(
        f"[+] G/S registered at operator with {op_id:x}:{op_secret:x}")


async def set_broadcast_msg(conn: Connection, *args):
    global INFO

    if not INFO.gs_is_registered():
        print("[-] Please register a ground station first")
        return

    if len(args) < 2:
        print(HELP[3])
        return

    slot = args[0]
    msg = " ".join(args[1:])

    if not slot.isnumeric():
        print("[-] The slot has to be a number between 0 and 255")
        return
    slot = int(slot)

    slots_needed = (len(msg) + BROADCAST_MESSAGE_SIZE -
                    1) // BROADCAST_MESSAGE_SIZE
    if slot + slots_needed > 0xff:
        print("[-] The message could not fit into the 255 broadcast message slots")
        return

    for x in range(slots_needed):
        msg_chunk = msg[x*BROADCAST_MESSAGE_SIZE:(x+1)*BROADCAST_MESSAGE_SIZE]
        set_msg = SetBroadcastMessage(
            INFO.gs_id, INFO.password, msg_chunk, slot + x)
        set_msg_ret = SetBroadcastMessageResponse(await conn.send(set_msg.prepare_message()))
        if set_msg_ret.error != ErrorCode.Success:
            print(f"[-] Could not set message in chunk {x}")

    print("[+] Message has been set")


async def get_broadcast_msg(conn: Connection, *args):
    global INFO

    if len(args) < 1:
        print(HELP[4])
        return

    if not INFO.gs_is_registered():
        print("[-] Please register a ground station first")
        return

    slot = args[0]
    if not slot.isnumeric():
        print("[-] The slot has to be a number between 0 and 255")
        return
    slot = int(slot)

    other_id = INFO.gs_id
    if len(args) > 1:
        other_id = args[1]
        try:
            other_id = int(other_id, 16)
        except ValueError:
            print("[-] The experiment id has to be a hex integer")
            return

    get_msg = ReadBroadcastMessage(INFO.gs_id, INFO.password, other_id, slot)
    get_msg_ret = ReadBroadcastMessageResponse(await conn.send(get_msg.prepare_message()))

    if get_msg_ret.error != ErrorCode.Success:
        print(f"[-] Could not get the message for slot {slot}: {get_msg_ret}")
        return

    print(f"[+] Got a message: {get_msg_ret.message}")


async def create_experiment(conn: Connection, *args):
    global INFO

    if not INFO.gs_is_registered():
        print("[-] Please register a ground station first")
        return

    run_exp = UsePayload(INFO.gs_id, INFO.password)
    run_exp_ret = UsePayloadResponse(await conn.send(run_exp.prepare_message()))

    if run_exp_ret.error != ErrorCode.Success:
        print("[-] Could not use the payload to creat an experiment")
        return

    tag = " ".join(args).encode()
    if tag:
        chunks_needed = (len(tag) + EXPERIMENT_TAG_CHUNK_SIZE -
                         1) // EXPERIMENT_TAG_CHUNK_SIZE
        for chunk in range(chunks_needed):
            tag_chunk = tag[chunk * EXPERIMENT_TAG_CHUNK_SIZE:
                            (chunk+1) * EXPERIMENT_TAG_CHUNK_SIZE]
            tag_exp = TagExperiment(INFO.gs_id, INFO.password,
                                    run_exp_ret.experiment_id, tag_chunk)
            tag_exp_ret = TagExperimentResponse(await conn.send(tag_exp.prepare_message()))
            if tag_exp_ret.error != ErrorCode.Success:
                print(f"[-] Could not create tag chunk {chunk}")

    print(
        f"[+] Successfully created an experiment with ID: {run_exp_ret.experiment_id:x}")


async def downlink(conn: Connection, *args):
    global INFO

    if not INFO.gs_is_registered():
        print("[-] Please register a ground station first")
        return

    if len(args) < 1:
        print(HELP[6])
        return

    exp_id = args[0]
    try:
        exp_id = int(exp_id, 16)
    except ValueError:
        print("[-] The experiment id has to be a hex integer")
        return

    encrypted = False
    if len(args) >= 2:
        encrypted = True
        ogs_id = args[1]
        try:
            ogs_id = int(ogs_id, 16)
        except ValueError:
            print("[-] The ground station id has to be a hex integer")
            return
    else:
        ogs_id = INFO.gs_id

    num_chunks = RequestChunkAmount(INFO.gs_id, INFO.password, ogs_id, exp_id)
    num_chunks_ret = RequestChunkAmountResponse(await conn.send(num_chunks.prepare_message()))

    if num_chunks_ret.error != ErrorCode.Success:
        print("[-] Could not retrieve the amount of chunks")
        return

    ret = b""
    for chunk in range(num_chunks_ret.chunk_amount):
        if encrypted:
            msg_chunk = RequestAssistedDownlink(
                INFO.gs_id, ogs_id, exp_id, chunk)
            msg_chunk_ret = RequestAssistedDownlinkResponse(await conn.send(msg_chunk.prepare_message()))
            if num_chunks_ret.error != ErrorCode.Success:
                print(f"[-] Could not get chunk {chunk}")
                ret += b"X" * DOWNLINK_CHUNK_SIZE
                continue
            ret += msg_chunk_ret.data
        else:
            msg_chunk = RequestDownlink(
                INFO.gs_id, INFO.password, exp_id, chunk)
            msg_chunk_ret = RequestDownlinkResponse(await conn.send(msg_chunk.prepare_message()))
            if num_chunks_ret.error != ErrorCode.Success:
                print(f"[-] Could not get chunk {chunk}")
                ret += b"X" * DOWNLINK_CHUNK_SIZE
                continue
            ret += msg_chunk_ret.data

    print(
        f"[+] Got the following message{' (encrypted)' if encrypted else ''}:")
    print(ret.hex() if encrypted else ret)


async def decrypt_downlink(conn: Connection, *args):
    global INFO

    if not INFO.gs_is_registered():
        print("[-] Please register a ground station first")
        return

    if len(args) < 2:
        print(HELP[7])
        return

    exp_id = args[0]
    try:
        exp_id = int(exp_id, 16)
    except ValueError:
        print("[-] The experiment id has to be a hex integer")
        return

    data = args[1]
    try:
        data = bytes.fromhex(data)
    except ValueError:
        print("[-] The data has to be a hex string")
        return

    key_msg = RequestAssistedDownlinkKey(INFO.gs_id, INFO.password, exp_id)
    key_msg_ret = RequestAssistedDownlinkKeyResponse(await conn.send(key_msg.prepare_message()))
    if key_msg_ret.error != ErrorCode.Success:
        print("[-] Could not retrieve the decryption key")
        return

    key = key_msg_ret.key
    ret = b""
    num_chunks = (len(data) + DOWNLINK_CHUNK_SIZE - 1) // DOWNLINK_CHUNK_SIZE

    for chunk in range(num_chunks):
        aes = AES.new(key, AES.MODE_CTR, nonce=b"", initial_value=chunk*2)
        ret += aes.decrypt(data[chunk*DOWNLINK_CHUNK_SIZE:
                           (chunk+1)*DOWNLINK_CHUNK_SIZE])

    print("[+] Decrypted message:")
    print(ret)


def print_help():
    print(EXPLANATION)
    print()
    print("<> = required, [] = optional")
    print("\n".join(HELP))


async def main():
    ip = input("Welcome to heavensent.\nPlease enter an IP to connect to > ")
    async with Connection(ip, get_port_pool()) as conn:
        print(f"\nWelcome @ {ip}")
        while True:
            choice = input(
                (f"{INFO.gs_id:x} " if INFO.gs_id is not None else "") + "> ")

            args = choice.split(" ")[1:]
            choice = choice.split(" ")[0].lower()
            match choice:
                case "reg_ground_station":
                    await register_ground_station(conn, *args)
                case "reg_operator":
                    await register_gs_at_op(conn, *args)
                case "send_broadcast":
                    await set_broadcast_msg(conn, *args)
                case "recv_broadcast":
                    await get_broadcast_msg(conn, *args)
                case "run_experiment":
                    await create_experiment(conn, *args)
                case "downlink":
                    await downlink(conn, *args)
                case "decrypt_downlink":
                    await decrypt_downlink(conn, *args)
                case "switch_ground":
                    change_ground_station(*args)
                case "q":
                    break
                case "?" | "help":
                    print_help()
                case _:
                    print(f"[-] Invalid command: {choice.split(' ')[0]}")

            print()


if __name__ == "__main__":
    print(BANNER)
    asyncio.run(main())
