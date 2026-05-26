from annotated_types import Ge, Lt
from ipaddress import IPv4Address, IPv6Address
from flask import session
from pydantic import AfterValidator, Base64Bytes, BaseModel, Field
from pydantic import ValidationError as PydanticValidationError
from pydantic.types import PositiveInt
from struct import pack
from typing import Annotated

SUBID = Annotated[int, Ge(0), Lt(2**32)]


class ValidationError(ValueError):
    """
    Custom exception to be used in validators.
    This needs to be json serializable via the flask default json serializer
    so define the __html__ method to not generate any errors
    """

    def __html__(self):
        return self.args[0]


def is_byte_decodable(value: str):
    try:
        bytes.fromhex(value)
    except ValueError:
        raise ValidationError("String is not hex decodable")
    return value


class AdvancedGet(BaseModel):
    data: Annotated[str, AfterValidator(is_byte_decodable)] = Field(pattern="^[0-9A-Fa-f]+$")


class AdvancedResponse(BaseModel):
    value: str
    code: int = 200


class CustomGet(BaseModel):
    identifier: str = Field(
        pattern="^[0-9A-Fa-f]+$",
        min_length=16,
        max_length=16,
        default_factory=lambda: pack(">q", session["identifier"]).hex(),
    )
    secret: str = Field(pattern="^[0-9A-Fa-f]+$", min_length=16, max_length=16)


class CustomPost(BaseModel):
    secret: str = Field(pattern="^[0-9A-Fa-f]+$", min_length=16, max_length=16)
    value: Base64Bytes


class CustomResponse(BaseModel):
    identifier: str
    value: Base64Bytes
    code: int = 200


class MonitoringGet(BaseModel):
    label: str


class MonitoringResponse(BaseModel):
    value: str | int | None
    code: int = 200


class MonitoringInitResponse(BaseModel):
    values: dict[str, str]
    code: int = 200
