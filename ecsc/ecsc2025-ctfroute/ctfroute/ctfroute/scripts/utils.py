from typing import Optional

from pydantic import ConfigDict

from ctfroute.adapters.yaml_conf import YamlConfig
from ctfroute.state.base import CtfRouteBaseModel


class HelmValues(CtfRouteBaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    ctf: Optional[str] = None
    network_index: int
    ctfroute: YamlConfig
