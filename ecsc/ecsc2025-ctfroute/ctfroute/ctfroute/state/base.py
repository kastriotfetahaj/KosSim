from abc import ABC

from pydantic import AliasGenerator, BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CtfRouteBaseModel(BaseModel, ABC):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        alias_generator=AliasGenerator(
            validation_alias=to_camel,
            serialization_alias=to_camel,
        ),
    )


class TeamConnectivity(CtfRouteBaseModel, ABC):
    driver: str


class RouterConnectivity(CtfRouteBaseModel, ABC):
    driver: str


class Anonymization(CtfRouteBaseModel, ABC):
    driver: str
