__all__ = ["HostnameRouterConnectivity"]
from typing import Literal

from ctfroute.state.base import RouterConnectivity


class HostnameRouterConnectivity(RouterConnectivity):
    driver: Literal["hostname"]
