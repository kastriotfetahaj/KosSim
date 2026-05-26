from socket import *
from struct import pack_into, pack, unpack
from enum import IntEnum
from Crypto.Cipher import AES

import secrets

FRAME_LEN = 64
HEADER_LEN = 4


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
    RequestDownlink = 5
    RequestAssistedDownlink = 6
    RequestAssistedDownlinkKey = 7
    UsePayload = 8

    RegisterOperatorResponse = 0x80
    RegisterAtOperatorResponse = 0x81
    RegisterGroundStationResponse = 0x82
    SetBroadcastMessageResponse = 0x83
    ReadBroadcastMessageResponse = 0x84
    AssistedDownlinkKeyResponse = 0x85
    UsePayloadResponse = 0x86

    DownlinkMetadataResponse = 0x95
    DownlinkChunkResponse = 0x96


class Request:
    def prepare_message(self):
        self.message_id = secrets.randbits(16)
        return bytes(self)


class Response:
    def __init__(self, data):
        self.type, self.message_id, self.error = unpack(
            ">BHB", data[:HEADER_LEN])
        self.type = Function(self.type)
        self.error = ErrorCode(self.error)
        self.data = data[HEADER_LEN:]

    def __repr__(self):
        if self.error == ErrorCode.Success:
            return f"Type={self.type.name}, Message ID={self.message_id:#x}"


class RegisterOperator(Request):
    def __init__(self, gs_id=0x1337):
        self.gs_id = gs_id
        self.req_id = Function.RegisterOperator

    def __bytes__(self):
        ret = bytearray(FRAME_LEN)
        pack_into(">BHQ", ret, 0, self.req_id, self.message_id, self.gsid)
        return bytes(ret)


class RegisterOperatorResponse(Response):
    def __init__(self, data):
        super().__init__(data)
        assert (self.type == Function.RegisterOperatorResponse)

        self.op_id, self.op_secret = unpack(">QQ", self.data[:0x10])

    def __repr__(self):
        if self.error == ErrorCode.Success:
            return f"RegisterOperator(GSID={self.gsid:#x}, OPID={self.op_id:#x}, " + \
                f"OP Secret: {self.op_secret:x})"
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

    def __bytes__(self):
        ret = bytearray(FRAME_LEN)
        pack_into(">BHQ", ret, 0, Function.RegisterGroundStation,
                  self.message_id, self.password)
        return bytes(ret)


class RegisterGroundStationResponse(Response):
    def __init__(self, data):
        super().__init__(data)
        assert (self.type == Function.RegisterGroundStationResponse)
        self.gs_id = unpack(">Q", self.data[:8])[0]

    def __repr__(self):
        if self.error == ErrorCode.Success:
            return f"RegisterGroundStation(GSID={self.gs_id:#x})"
        return f"RegisterOperator(Error={self.error.name})"


class RegisterOperator(Request):
    def __init__(self, gs_id):
        self.gs_id = gs_id

    def __bytes__(self):
        ret = bytearray(FRAME_LEN)
        pack_into(">BHQ", ret, 0, Function.RegisterOperator,
                  self.message_id, self.gs_id)
        return bytes(ret)


class RegisterOperatorResponse(Response):
    def __init__(self, data):
        super().__init__(data)
        assert (self.type == Function.RegisterOperatorResponse)
        self.op_id, self.op_secret = unpack(">QQ", self.data[:0x10])

    def __repr__(self):
        if self.error == ErrorCode.Success:
            return f"RegisterOperator(OPID={self.op_id:#x}, Secret={self.op_secret:#x})"
        return f"RegisterOperator(Error={self.error.name})"


class RegisterAtOperator(Request):
    def __init__(self, gs_id, op_id, op_secret):
        self.gs_id = gs_id
        self.op_id = op_id
        self.op_secret = op_secret

    def __bytes__(self):
        ret = bytearray(FRAME_LEN)
        pack_into(">BHQQQ", ret, 0, Function.RegisterAtOperator, self.message_id, self.gs_id,
                  self.op_id, self.op_secret)
        return bytes(ret)


class RegisterAtOperatorResponse(Response):
    def __init__(self, data):
        super().__init__(data)
        assert (self.type == Function.RegisterAtOperatorResponse)

    def __repr__(self):
        if self.error == ErrorCode.Success:
            return f"RegisterAtOperator(Success)"
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
        pack_into(">BHQQB", ret, 0, Function.SetBroadcastMessage, self.message_id, self.gs_id,
                  self.password, self.slot)
        for i in range(min(len(self.message), 32)):
            ret[i + 20] = self.message[i]
        return bytes(ret)


class SetBroadcastMessageResponse(Response):
    def __init__(self, data):
        super().__init__(data)
        assert (self.type == Function.SetBroadcastMessageResponse)

    def __repr__(self):
        if self.error == ErrorCode.Success:
            return f"SetBroadcastMessage(Success)"
        return f"SetBroadcastMessage(Error={self.error.name})"


class ReadBroadcastMessage(Request):
    def __init__(self, gs_id, password, ogs_id, slot):
        self.gs_id = gs_id
        self.password = password
        self.slot = slot
        self.ogs_id = ogs_id

    def __bytes__(self):
        ret = bytearray(FRAME_LEN)
        pack_into(">BHQQQB", ret, 0, Function.ReadBroadcastMessage, self.message_id, self.gs_id,
                  self.password, self.ogs_id, self.slot)
        return bytes(ret)


class ReadBroadcastMessageResponse(Response):
    def __init__(self, data):
        super().__init__(data)
        assert (self.type == Function.ReadBroadcastMessageResponse)
        self.message = self.data[:0x20]

    def __repr__(self):
        if self.error == ErrorCode.Success:
            return f"ReadBroadcastMessage(Message={self.message})"
        return f"ReadBroadcastMessage(Error={self.error.name})"


class UsePayload(Request):
    def __init__(self, gs_id, metadata):
        assert (len(metadata) < 54)
        if isinstance(metadata, str):
            metadata = metadata.encode()
        self.metadata = metadata
        self.gs_id = gs_id

    def __bytes__(self):
        ret = bytearray(FRAME_LEN)
        pack_into(">BHQ", ret, 0, Function.UsePayload,
                  self.message_id, self.gs_id)
        for i, x in enumerate(self.metadata):
            ret[i + 11] = x
        return bytes(ret)


class UsePayloadResponse(Response):
    def __init__(self, data):
        super().__init__(data)
        assert (self.type == Function.UsePayloadResponse)
        self.experiment_id = unpack(">Q", self.data[:8])[0]

    def __repr__(self):
        if self.error == ErrorCode.Success:
            return f"UsePayload(ExperimentID={self.experiment_id:#x})"
        return f"UsePayload(Error={self.error.name})"


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
                  self.message_id, self.gs_id, self.password, self.e_id, self.chunk)
        return bytes(ret)


class RequestDownlinkResponse(Response):
    def __init__(self, data):
        super().__init__(data)
        self.chunk = unpack(">i", self.data[:4])[0]
        if self.chunk == -1:
            assert (self.type == Function.DownlinkMetadataResponse)
            self.chunk_amount = unpack(">B", self.data[4:5])[0]
        else:
            assert (self.type == Function.DownlinkChunkResponse)
            self.data = self.data[4:36]

    def __repr__(self):
        if self.error == ErrorCode.Success and self.chunk == -1:
            return f"RequestDownlink(Amount={self.chunk_amount})"
        elif self.error == ErrorCode.Success:
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
                  self.message_id, self.gs_id, self.other_gs_id, self.e_id, self.chunk)
        return bytes(ret)


class RequestAssistedDownlinkResponse(Response):
    def __init__(self, data):
        super().__init__(data)
        self.chunk = unpack(">i", self.data[:4])[0]
        if self.chunk == -1:
            assert (self.type == Function.DownlinkMetadataResponse)
            self.chunk_amount = unpack(">B", self.data[4:5])[0]
        else:
            assert (self.type == Function.DownlinkChunkResponse)
            self.data = self.data[4:36]

    def __repr__(self):
        if self.error == ErrorCode.Success and self.chunk == -1:
            return f"RequestAssistedDownlink(Amount={self.chunk_amount})"
        elif self.error == ErrorCode.Success:
            return f"RequestAssistedDownlink(Chunk={self.chunk}, Data={self.data})"
        return f"RequestAssistedDownlink(Error={self.error.name})"


class RequstAssistedDownlinkKey(Request):
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
        super().__init__(data)
        self.key = self.data[:16]

    def __repr__(self):
        if self.error == ErrorCode.Success:
            return f"RequestAssistedDownlinkKey(Key={self.key.hex()})"
        return f"RequestAssistedDownlinkKey(Error={self.error.name})"


def send(payload, verbose=True):
    if isinstance(payload, str):
        payload = payload.encode()

    sock = socket(AF_INET, SOCK_STREAM)
    sock.connect(("localhost", 9502))
    if verbose:
        print("[DEBUG TX]", payload.hex())
    sock.send(payload)
    ret = sock.recv(len(payload))
    if verbose:
        print("[DEBUG RX]", ret.hex())
    sock.close()
    return ret


msg1 = RegisterGroundStation()
msg1_ret = RegisterGroundStationResponse(send(msg1.prepare_message()))
print(msg1_ret)

msg9 = RegisterGroundStation()
msg9_ret = RegisterGroundStationResponse(send(msg9.prepare_message()))

msg2 = UsePayload(msg1_ret.gs_id, "TESTDATA")
msg2_ret = UsePayloadResponse(send(msg2.prepare_message()))
print(msg2_ret)

chunk_id = 2
msg3 = RequestAssistedDownlink(
    msg9_ret.gs_id, msg1_ret.gs_id, msg2_ret.experiment_id, chunk_id)
msg3_ret = RequestAssistedDownlinkResponse(send(msg3.prepare_message()))
print(msg3_ret)

msg4 = RequstAssistedDownlinkKey(msg1_ret.gs_id, msg1.password, msg2_ret.experiment_id)
msg4_ret = RequestAssistedDownlinkKeyResponse(
    send(msg4.prepare_message(), True))
print(msg4_ret)

print("key", msg4_ret.key.hex())
print("data", msg3_ret.data.hex())
cipher = AES.new(msg4_ret.key, AES.MODE_CTR, nonce=b"", initial_value=chunk_id*2)
print(cipher.decrypt(msg3_ret.data))
