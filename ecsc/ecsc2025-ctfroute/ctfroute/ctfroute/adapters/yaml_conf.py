from pathlib import Path
from typing import Annotated, Any, Literal, Optional

from pydantic import Field
from yaml import safe_load

from ctfroute.drivers.hostname.state import HostnameRouterConnectivity
from ctfroute.drivers.netfilter.state import NetfilterAnonymization
from ctfroute.exceptions import BadConfiguration
from ctfroute.state import external
from ctfroute.state.base import (
    CtfRouteBaseModel,
)
from ctfroute.utils import EntityType


class HttpAdapterConfig(CtfRouteBaseModel):
    type: Literal["http"]
    poll_interval: float = 1.0
    url: str
    entity_types: list[EntityType]


class KubernetesAdapterConfig(CtfRouteBaseModel):
    type: Literal["kubernetes"] = "kubernetes"
    namespace: str
    # TODO: Support this similar to http adapter
    # entity_types:


AdapterUnion = HttpAdapterConfig | KubernetesAdapterConfig


class InstanceConfig(CtfRouteBaseModel):
    router_id: external.RouterId | None = None
    # logging config as described here:
    # https://docs.python.org/3/library/logging.config.html#logging-config-dictschema
    logging: dict[str, Any] | None = None
    # If None, no metrics are exposed.
    # If existing dir, will write metrics to router-${id}.prom
    # Else will write metrics to that path
    metrics: Optional[Path] = None


class TeamDefaults(CtfRouteBaseModel):
    anonymization: Optional[NetfilterAnonymization] = None


class RouterDefaults(CtfRouteBaseModel):
    connectivity: Optional[HostnameRouterConnectivity] = None


class DefaultsConfig(CtfRouteBaseModel):
    teams: Optional[TeamDefaults] = None
    routers: Optional[RouterDefaults] = None


class YamlConfig(CtfRouteBaseModel):
    """Used to deserialize ctfroute.yml config files."""

    model_config = {
        **CtfRouteBaseModel.model_config,
        # TODO: remove this once we cover all the features in our example file
        #  (templates, etc.)
        "extra": "allow",
    }

    adapters: list[Annotated[AdapterUnion, Field(discriminator="type")]] = Field(
        default_factory=list
    )
    instance: Optional[InstanceConfig] = None
    defaults: Optional[DefaultsConfig] = None
    initial_state: external.CtfRouteState


def validate_yaml_conf(config: YamlConfig, write_defaults: bool = True):
    default_anon = default_router_conn = None

    # Copy default drivers to respective entities
    if config.defaults:
        if config.defaults.teams:
            default_anon = config.defaults.teams.anonymization
        if config.defaults.routers:
            default_router_conn = config.defaults.routers.connectivity

    for team in config.initial_state.teams:
        if team.anonymization is None and default_anon is None:
            raise BadConfiguration(
                f"Team {team.id} has no anonymization driver and no default is set."
            )
        elif team.anonymization is None and write_defaults:
            team.anonymization = default_anon

    for router in config.initial_state.routers:
        if router.connectivity is None and default_router_conn is None:
            raise BadConfiguration(
                f"Router {router.id} has no connectivity driver and no default is set."
            )
        elif router.connectivity is None and write_defaults:
            router.connectivity = default_router_conn


def read_yaml_conf(file: Path) -> YamlConfig:
    config: YamlConfig = YamlConfig.model_validate(safe_load(file.read_text()))
    validate_yaml_conf(config, write_defaults=True)
    return config
