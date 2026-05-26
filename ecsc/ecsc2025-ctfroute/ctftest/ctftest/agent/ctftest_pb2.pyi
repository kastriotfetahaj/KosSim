from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ListenStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    READY: _ClassVar[ListenStatus]
    DONE: _ClassVar[ListenStatus]

class SniffStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    STARTED: _ClassVar[SniffStatus]
    STOPPED_BY_LIMIT: _ClassVar[SniffStatus]
    STOPPED_MANUALLY: _ClassVar[SniffStatus]
    NOT_FOUND: _ClassVar[SniffStatus]
READY: ListenStatus
DONE: ListenStatus
STARTED: SniffStatus
STOPPED_BY_LIMIT: SniffStatus
STOPPED_MANUALLY: SniffStatus
NOT_FOUND: SniffStatus

class PingRequest(_message.Message):
    __slots__ = ("target", "timeout", "retries")
    TARGET_FIELD_NUMBER: _ClassVar[int]
    TIMEOUT_FIELD_NUMBER: _ClassVar[int]
    RETRIES_FIELD_NUMBER: _ClassVar[int]
    target: str
    timeout: int
    retries: int
    def __init__(self, target: _Optional[str] = ..., timeout: _Optional[int] = ..., retries: _Optional[int] = ...) -> None: ...

class PingResponse(_message.Message):
    __slots__ = ("success",)
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    success: bool
    def __init__(self, success: bool = ...) -> None: ...

class ListenRequest(_message.Message):
    __slots__ = ("port", "echo", "collect", "amount")
    PORT_FIELD_NUMBER: _ClassVar[int]
    ECHO_FIELD_NUMBER: _ClassVar[int]
    COLLECT_FIELD_NUMBER: _ClassVar[int]
    AMOUNT_FIELD_NUMBER: _ClassVar[int]
    port: int
    echo: bool
    collect: bool
    amount: int
    def __init__(self, port: _Optional[int] = ..., echo: bool = ..., collect: bool = ..., amount: _Optional[int] = ...) -> None: ...

class ListenResponse(_message.Message):
    __slots__ = ("status", "client", "src_port", "duration", "amount", "message")
    STATUS_FIELD_NUMBER: _ClassVar[int]
    CLIENT_FIELD_NUMBER: _ClassVar[int]
    SRC_PORT_FIELD_NUMBER: _ClassVar[int]
    DURATION_FIELD_NUMBER: _ClassVar[int]
    AMOUNT_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    status: ListenStatus
    client: str
    src_port: int
    duration: float
    amount: int
    message: bytes
    def __init__(self, status: _Optional[_Union[ListenStatus, str]] = ..., client: _Optional[str] = ..., src_port: _Optional[int] = ..., duration: _Optional[float] = ..., amount: _Optional[int] = ..., message: _Optional[bytes] = ...) -> None: ...

class SendRequest(_message.Message):
    __slots__ = ("target", "port", "message", "echo_recv", "echo_collect", "connect_timeout")
    TARGET_FIELD_NUMBER: _ClassVar[int]
    PORT_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    ECHO_RECV_FIELD_NUMBER: _ClassVar[int]
    ECHO_COLLECT_FIELD_NUMBER: _ClassVar[int]
    CONNECT_TIMEOUT_FIELD_NUMBER: _ClassVar[int]
    target: str
    port: int
    message: bytes
    echo_recv: bool
    echo_collect: bool
    connect_timeout: int
    def __init__(self, target: _Optional[str] = ..., port: _Optional[int] = ..., message: _Optional[bytes] = ..., echo_recv: bool = ..., echo_collect: bool = ..., connect_timeout: _Optional[int] = ...) -> None: ...

class SendResponse(_message.Message):
    __slots__ = ("success", "duration", "response", "status")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    DURATION_FIELD_NUMBER: _ClassVar[int]
    RESPONSE_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    success: bool
    duration: float
    response: bytes
    status: str
    def __init__(self, success: bool = ..., duration: _Optional[float] = ..., response: _Optional[bytes] = ..., status: _Optional[str] = ...) -> None: ...

class IperfRequest(_message.Message):
    __slots__ = ("address", "port", "server", "duration")
    ADDRESS_FIELD_NUMBER: _ClassVar[int]
    PORT_FIELD_NUMBER: _ClassVar[int]
    SERVER_FIELD_NUMBER: _ClassVar[int]
    DURATION_FIELD_NUMBER: _ClassVar[int]
    address: str
    port: int
    server: bool
    duration: int
    def __init__(self, address: _Optional[str] = ..., port: _Optional[int] = ..., server: bool = ..., duration: _Optional[int] = ...) -> None: ...

class IperfResponse(_message.Message):
    __slots__ = ("status", "json")
    STATUS_FIELD_NUMBER: _ClassVar[int]
    JSON_FIELD_NUMBER: _ClassVar[int]
    status: ListenStatus
    json: str
    def __init__(self, status: _Optional[_Union[ListenStatus, str]] = ..., json: _Optional[str] = ...) -> None: ...

class HttpGet(_message.Message):
    __slots__ = ("url", "timeout")
    URL_FIELD_NUMBER: _ClassVar[int]
    TIMEOUT_FIELD_NUMBER: _ClassVar[int]
    url: str
    timeout: int
    def __init__(self, url: _Optional[str] = ..., timeout: _Optional[int] = ...) -> None: ...

class HttpResponse(_message.Message):
    __slots__ = ("status_code", "body")
    STATUS_CODE_FIELD_NUMBER: _ClassVar[int]
    BODY_FIELD_NUMBER: _ClassVar[int]
    status_code: int
    body: bytes
    def __init__(self, status_code: _Optional[int] = ..., body: _Optional[bytes] = ...) -> None: ...

class StartSniffRequest(_message.Message):
    __slots__ = ("filter", "seconds")
    FILTER_FIELD_NUMBER: _ClassVar[int]
    SECONDS_FIELD_NUMBER: _ClassVar[int]
    filter: str
    seconds: int
    def __init__(self, filter: _Optional[str] = ..., seconds: _Optional[int] = ...) -> None: ...

class StartSniffResponse(_message.Message):
    __slots__ = ("uuid",)
    UUID_FIELD_NUMBER: _ClassVar[int]
    uuid: str
    def __init__(self, uuid: _Optional[str] = ...) -> None: ...

class StopSniffRequest(_message.Message):
    __slots__ = ("uuid",)
    UUID_FIELD_NUMBER: _ClassVar[int]
    uuid: str
    def __init__(self, uuid: _Optional[str] = ...) -> None: ...

class StopSniffResponse(_message.Message):
    __slots__ = ("status",)
    STATUS_FIELD_NUMBER: _ClassVar[int]
    status: SniffStatus
    def __init__(self, status: _Optional[_Union[SniffStatus, str]] = ...) -> None: ...

class SniffRecordingRequest(_message.Message):
    __slots__ = ("uuid",)
    UUID_FIELD_NUMBER: _ClassVar[int]
    uuid: str
    def __init__(self, uuid: _Optional[str] = ...) -> None: ...

class SniffRecordingResponse(_message.Message):
    __slots__ = ("status", "recording")
    STATUS_FIELD_NUMBER: _ClassVar[int]
    RECORDING_FIELD_NUMBER: _ClassVar[int]
    status: SniffStatus
    recording: bytes
    def __init__(self, status: _Optional[_Union[SniffStatus, str]] = ..., recording: _Optional[bytes] = ...) -> None: ...
