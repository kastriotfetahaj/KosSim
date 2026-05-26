__all__ = ["NetfilterAnonymization"]
from typing import Literal

from ctfroute.state.base import Anonymization


class NetfilterAnonymization(Anonymization):
    driver: Literal["netfilter"] = "netfilter"
