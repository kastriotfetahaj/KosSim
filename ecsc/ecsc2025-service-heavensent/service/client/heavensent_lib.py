from struct import pack_into, unpack
from enum import IntEnum
import inspect
import secrets
import time

import asyncio

FRAME_LEN = 64
HEADER_LEN = 4

SERVICE_PORT = 9500

DOPPLER_MAX = 10000

class Connection:
    def __init__(self, remote_ip, port_pool, flow_graph="./heavensent_client.py", log=print):
        self.remote_ip = remote_ip
        self.port_pool = port_pool
        self.flow_graph = flow_graph
        self.log = log

    async def connect(self):
        self.local_port = await self.port_pool.get()
        doppler = (secrets.randbelow(2 * 10 * DOPPLER_MAX) / 10) - DOPPLER_MAX
        self.proc = await asyncio.create_subprocess_exec(
            "python3", self.flow_graph,
            "--client-port", str(self.local_port),
            "--service-host", self.remote_ip,
            "--doppler-hz", str(doppler),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # The process is now running. From now until the end of the function, we must
        # ensure that we properly clean up after ourselves, as we will be called from
        # __aenter__, and an exception in __aenter__ does not call __aexit__!
        try:
            async def runner():
                self.log(f"GNU Radio started (local_port={self.local_port}, flow_graph={self.flow_graph})")
                # while self.proc.returncode is None:
                #     self.log("Gnuradio alive")
                #     self.log(f"[GR] {await proc.stdout.readline()}")
                stdout, stderr = await self.proc.communicate()
                self.log(f"GNU Radio exited (local_port={self.local_port}, code={self.proc.returncode})")
                self.log("stdout: " + repr(stdout))
                self.log("stderr: " + repr(stderr))

                await self.port_pool.put(self.local_port)

            # Make sure we hold onto a reference to the task to avoid it being garbage-collected
            # See https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task
            self.runner_task = asyncio.create_task(runner())

            startup_time = 20
            startup_interval = .05
            tries = int(startup_time / startup_interval)

            for i in range(tries):
                try:
                    self.rx, self.tx = await asyncio.open_connection("127.0.0.1", self.local_port)
                    break
                except ConnectionRefusedError:
                    pass

                # Has GNU Radio has died already? Then we can stop trying.
                if self.proc.returncode is not None:
                    self.log("GNU Radio exited prematurely while waiting for connect")
                    raise ConnectionRefusedError

                await asyncio.sleep(startup_interval)
            else:
                raise ConnectionRefusedError

            await self.sync()
        except (Exception, asyncio.CancelledError) as e:
            # We either:
            # - got cancelled
            # - timed out on connecting to the flow graph
            # - timed out on synchronizing with the flow graph
            # - or something else went wrong
            # Either way, we should clean up the process so we don't leave lingering instances of GNU Radio
            await self.close()
            raise e

    async def sync(self):
        # Synchronize with the flow graph
        # This is a workaround for an issue with GNU Radio where if we send data
        # too soon, it will be dropped.
        sync_start_pc = time.perf_counter()

        sync_max_time = 5.0
        sync_initial_interval = 0.05

        sync_interval = sync_initial_interval
        sync_elapsed_time = 0
        sync_elapsed_retries = 0
        while True:
            # Signal we are waiting
            self.tx.write(b"W")
            await self.tx.drain()

            # See if we can get a response yet
            try:
                async with asyncio.timeout(sync_interval):
                    sync_response = (await self.rx.readexactly(1))[:1]

                # If we make it to here, we made it!
                break
            except asyncio.IncompleteReadError:
                self.log("GNU Radio closed connection prematurely while waiting for sync")
                raise ConnectionRefusedError
            except TimeoutError:
                pass

            # We did not manage to synchronize.
            # Do we have more time?
            sync_elapsed_time += sync_interval
            if sync_elapsed_time >= sync_max_time:
                self.log("Timed out waiting for sync with GNU Radio")
                # This will propagate outwards and then result in the error handling from connect()
                # This can happen in case GNU Radio failed to start up or the remote client is down too!
                raise ConnectionRefusedError

            # Increase our wait to avoid a condition where we indefinitely stall because the timeout
            # is just too short
            sync_elapsed_retries += 1
            sync_interval *= 2

        # GR should have replied "we are ready"
        if sync_response != b"R":
            self.log(f"Bad sync response from GNU Radio: {repr(sync_response)}")
            raise ConnectionRefusedError

        # Signal we would like to start now
        self.tx.write(b"S")
        await self.tx.drain()

        # Wait until GR has caught up with our wait requests and acknowledged sync.
        # This is critical as we cannot guarantee earlier timeouts were real and not just spurious
        try:
            ack_response = await self.rx.readuntil(b"A")
        except asyncio.IncompleteReadError:
            raise ConnectionRefusedError
        extra_ready_count = len(ack_response) - 1
        if ack_response != b"R" * extra_ready_count + b"A":
            self.log(f"Unexpected ack response: {ack_response}")
            raise ConnectionRefusedError

        sync_end_pc = time.perf_counter()
        sync_total_seconds = sync_end_pc - sync_start_pc

        self.log(f"Synchronized with flow graph after {sync_elapsed_retries} retries in {sync_total_seconds} seconds")

    async def close(self):
        # This function is safe from cancellation:
        # if we get cancelled, it can only be in the wait(), however at
        # that point kill() was already run and kill() sends its signal
        # immediately.
        try:
            self.proc.kill()
        except ProcessLookupError:
            # The process died already.
            pass
        await self.proc.wait()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False

    async def send(self, payload, verbose=False):
        if verbose:
            self.log(f"[DEBUG TX] {payload.hex()}")

        # TODO: try/except this to ensure we raise some uniform exception type?
        self.tx.write(payload)
        await self.tx.drain()
        ret = await self.rx.readexactly(FRAME_LEN)

        if verbose:
            self.log(f"[DEBUG RX] {ret.hex()}")
        return ret


class ErrorCode(IntEnum):
    UnknownError = 0xff
    Success = 0
    OperatorDoesNotExist = 1
    OperatorIDMissing = 2
    OperatorSecretWrong = 3
    GroundStationDoesNotExist = 4
    GroundStationIDMissing = 5
    GroundStationPasswordWrong = 6
    NotAuthorized = 7
    ExperimentDoesNotExist = 8
    BrokenRequest = 9


class Function(IntEnum):
    ErroroneousFunction = 0xff
    RegisterOperator = 0
    RegisterAtOperator = 1
    RegisterGroundStation = 2
    SetBroadcastMessage = 3
    ReadBroadcastMessage = 4
    RequestChunkAmount = 5
    RequestDownlink = 6
    RequestAssistedDownlink = 7
    RequestAssistedDownlinkKey = 8
    UsePayload = 9
    TagExperiment = 10

    RegisterOperatorResponse = 0x80
    RegisterAtOperatorResponse = 0x81
    RegisterGroundStationResponse = 0x82
    SetBroadcastMessageResponse = 0x83
    ReadBroadcastMessageResponse = 0x84
    RequestChunkAmountResponse = 0x85
    DownlinkChunkResponse = 0x86
    DownlinkAssistedChunkResponse = 0x87
    AssistedDownlinkKeyResponse = 0x88
    UsePayloadResponse = 0x89
    TagExperimentResponse = 0x8a


class Request:
    def prepare_message(self):
        self.message_id = secrets.randbits(16)
        return bytes(self)

    def __repr__(self):
        attributes = inspect.getmembers(
            self, lambda a: not (inspect.isroutine(a)))
        attributes = [a for a in attributes if not (
            a[0].startswith('__') and a[0].endswith('__'))]
        attributes = " ".join(f"{a[0]}={a[1]:x}" if "id" in a[0] or "passw" in a[0]
                              else f"{a[0]}={a[1]}" for a in attributes)
        return f"{type(self).__name__}({attributes})"


class Response:
    def __init__(self, data: bytes, response_type: Function):
        self.type, self.message_id, self.error = unpack(
            ">BHB", data[:HEADER_LEN])
        self.type = Function(self.type)
        if self.type != response_type:
            raise TypeError(f"Got type {self.type.name}, " +
                            f"wanted: {response_type.name}")

        self.error = ErrorCode(self.error)
        self.data = data[HEADER_LEN:]

    def __repr__(self):
        if self.error == ErrorCode.Success:
            return f"Type={self.type.name}, Message ID={self.message_id:#x}"


class RegisterOperator(Request):
    def __init__(self, gs_id, password):
        self.gs_id = gs_id
        self.password = password

    def __bytes__(self):
        ret = bytearray(FRAME_LEN)
        pack_into(">BHQQ", ret, 0, Function.RegisterOperator,
                  self.message_id, self.gs_id, self.password)
        return bytes(ret)


class RegisterOperatorResponse(Response):
    def __init__(self, data):
        super().__init__(data, Function.RegisterOperatorResponse)
        self.op_id, self.op_secret = unpack(">QQ", self.data[:0x10])

    def __repr__(self):
        if self.error == ErrorCode.Success:
            return f"RegisterOperator(OPID={self.op_id:#x}" + \
                f", Secret={self.op_secret:#x})"
        return f"RegisterOperator(Error={self.error.name})"


class RegisterGroundStation(Request):
    def __init__(self, password=None):
        if password is None:
            self.password = secrets.randbits(64)
        elif isinstance(password, int):
            self.password = password
        elif isinstance(password, str):
            self.password = unpack(">Q", bytes(password)[:8])
        elif isinstance(password, bytes):
            self.password = unpack(">Q", password[:8])
        else:
            assert False

    def __bytes__(self):
        ret = bytearray(FRAME_LEN)
        pack_into(">BHQ", ret, 0, Function.RegisterGroundStation,
                  self.message_id, self.password)
        return bytes(ret)


class RegisterGroundStationResponse(Response):
    def __init__(self, data):
        super().__init__(data, Function.RegisterGroundStationResponse)
        self.gs_id = unpack(">Q", self.data[:8])[0]

    def __repr__(self):
        if self.error == ErrorCode.Success:
            return f"RegisterGroundStation(GSID={self.gs_id:#x})"
        return f"RegisterOperator(Error={self.error.name})"


class RegisterAtOperator(Request):
    def __init__(self, gs_id, password, op_id, op_secret):
        self.gs_id = gs_id
        self.password = password
        self.op_id = op_id
        self.op_secret = op_secret

    def __bytes__(self):
        ret = bytearray(FRAME_LEN)
        pack_into(">BHQQQQ", ret, 0, Function.RegisterAtOperator,
                  self.message_id, self.gs_id, self.password, self.op_id, self.op_secret)
        return bytes(ret)


class RegisterAtOperatorResponse(Response):
    def __init__(self, data):
        super().__init__(data, Function.RegisterAtOperatorResponse)

    def __repr__(self):
        if self.error == ErrorCode.Success:
            return "RegisterAtOperator(Success)"
        return f"RegisterAtOperator(Error={self.error.name})"


class SetBroadcastMessage(Request):
    def __init__(self, gs_id, password, message, slot):
        if isinstance(message, str):
            message = message.encode()
        self.message = message
        self.gs_id = gs_id
        self.password = password
        self.slot = slot

    def __bytes__(self):
        ret = bytearray(FRAME_LEN)
        pack_into(">BHQQB", ret, 0, Function.SetBroadcastMessage,
                  self.message_id, self.gs_id, self.password, self.slot)
        for i in range(min(len(self.message), 32)):
            ret[i + 20] = self.message[i]
        return bytes(ret)


class SetBroadcastMessageResponse(Response):
    def __init__(self, data):
        super().__init__(data, Function.SetBroadcastMessageResponse)

    def __repr__(self):
        if self.error == ErrorCode.Success:
            return "SetBroadcastMessage(Success)"
        return f"SetBroadcastMessage(Error={self.error.name})"


class ReadBroadcastMessage(Request):
    def __init__(self, gs_id, password, ogs_id, slot):
        self.gs_id = gs_id
        self.password = password
        self.slot = slot
        self.ogs_id = ogs_id

    def __bytes__(self):
        ret = bytearray(FRAME_LEN)
        pack_into(">BHQQQB", ret, 0, Function.ReadBroadcastMessage,
                  self.message_id, self.gs_id, self.password, self.ogs_id,
                  self.slot)
        return bytes(ret)


class ReadBroadcastMessageResponse(Response):
    def __init__(self, data):
        super().__init__(data, Function.ReadBroadcastMessageResponse)
        self.message = self.data[:0x20]

    def __repr__(self):
        if self.error == ErrorCode.Success:
            return f"ReadBroadcastMessage(Message={self.message})"
        return f"ReadBroadcastMessage(Error={self.error.name})"


class UsePayload(Request):
    def __init__(self, gs_id, password):
        self.gs_id = gs_id
        self.password = password

    def __bytes__(self):
        ret = bytearray(FRAME_LEN)
        pack_into(">BHQQ", ret, 0, Function.UsePayload,
                  self.message_id, self.gs_id, self.password)
        return bytes(ret)


class UsePayloadResponse(Response):
    def __init__(self, data):
        super().__init__(data, Function.UsePayloadResponse)
        self.experiment_id = unpack(">Q", self.data[:8])[0]

    def __repr__(self):
        if self.error == ErrorCode.Success:
            return f"UsePayload(ExperimentID={self.experiment_id:#x})"
        return f"UsePayload(Error={self.error.name})"


class TagExperiment(Request):
    def __init__(self, gs_id, password, exp_id, tag):
        assert len(tag) <= 32
        self.gs_id = gs_id
        self.password = password
        self.exp_id = exp_id
        self.tag = tag

    def __bytes__(self):
        ret = bytearray(FRAME_LEN)
        pack_into(">BHQQQ", ret, 0, Function.TagExperiment,
                  self.message_id, self.gs_id, self.password, self.exp_id)
        for i, x in enumerate(self.tag):
            ret[i + 27] = x
        return bytes(ret)


class TagExperimentResponse(Response):
    def __init__(self, data):
        super().__init__(data, Function.TagExperimentResponse)

    def __repr__(self):
        if self.error == ErrorCode.Success:
            return "UsePayload(Success)"
        return f"UsePayload(Error={self.error.name})"


class RequestChunkAmount(Request):
    def __init__(self, gs_id, password, ogs_id, e_id):
        if isinstance(password, str):
            password = password.encode()
        self.e_id = e_id
        self.gs_id = gs_id
        self.password = password
        self.ogs_id = ogs_id

    def __bytes__(self):
        ret = bytearray(FRAME_LEN)
        pack_into(">BHQQQQ", ret, 0, Function.RequestChunkAmount,
                  self.message_id, self.gs_id, self.password, self.ogs_id,
                  self.e_id)
        return bytes(ret)


class RequestChunkAmountResponse(Response):
    def __init__(self, data):
        super().__init__(data, Function.RequestChunkAmountResponse)
        self.chunk_amount = self.data[0]

    def __repr__(self):
        if self.error == ErrorCode.Success:
            return f"RequestDownlink(Amount={self.chunk_amount})"
        return f"RequestDownlink(Error={self.error.name})"


class RequestDownlink(Request):
    def __init__(self, gs_id, password, e_id, chunk):
        if isinstance(password, str):
            password = password.encode()
        self.e_id = e_id
        self.gs_id = gs_id
        self.password = password
        self.chunk = chunk

    def __bytes__(self):
        ret = bytearray(FRAME_LEN)
        pack_into(">BHQQQi", ret, 0, Function.RequestDownlink,
                  self.message_id, self.gs_id, self.password, self.e_id,
                  self.chunk)
        return bytes(ret)


class RequestDownlinkResponse(Response):
    def __init__(self, data):
        super().__init__(data, Function.DownlinkChunkResponse)
        self.chunk = unpack(">i", self.data[:4])[0]
        self.data = self.data[4:36]

    def __repr__(self):
        if self.error == ErrorCode.Success:
            return f"RequestDownlink(Chunk={self.chunk}, Data={self.data})"
        return f"RequestDownlink(Error={self.error.name})"


class RequestAssistedDownlink(Request):
    def __init__(self, gs_id, other_gs_id, e_id, chunk):
        self.gs_id = gs_id
        self.other_gs_id = other_gs_id
        self.e_id = e_id
        self.chunk = chunk

    def __bytes__(self):
        ret = bytearray(FRAME_LEN)
        pack_into(">BHQQQi", ret, 0, Function.RequestAssistedDownlink,
                  self.message_id, self.gs_id, self.other_gs_id, self.e_id,
                  self.chunk)
        return bytes(ret)


class RequestAssistedDownlinkResponse(Response):
    def __init__(self, data):
        super().__init__(data, Function.DownlinkAssistedChunkResponse)
        self.chunk = unpack(">i", self.data[:4])[0]
        self.data = self.data[4:36]

    def __repr__(self):
        if self.error == ErrorCode.Success:
            return f"RequestAssistedDownlink(Chunk={self.chunk}" + \
                f", Data={self.data})"
        return f"RequestAssistedDownlink(Error={self.error.name})"


class RequestAssistedDownlinkKey(Request):
    def __init__(self, gs_id, password, exp_id):
        self.gs_id = gs_id
        self.password = password
        self.exp_id = exp_id

    def __bytes__(self):
        ret = bytearray(FRAME_LEN)
        pack_into(">BHQQQ", ret, 0, Function.RequestAssistedDownlinkKey,
                  self.message_id, self.gs_id, self.password, self.exp_id)
        return bytes(ret)


class RequestAssistedDownlinkKeyResponse(Response):
    def __init__(self, data):
        super().__init__(data, Function.AssistedDownlinkKeyResponse)
        self.key = self.data[:16]

    def __repr__(self):
        if self.error == ErrorCode.Success:
            return f"RequestAssistedDownlinkKey(Key={self.key.hex()})"
        return f"RequestAssistedDownlinkKey(Error={self.error.name})"
