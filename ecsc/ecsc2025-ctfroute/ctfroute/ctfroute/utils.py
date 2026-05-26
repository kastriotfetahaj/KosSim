import logging
from enum import StrEnum
from ipaddress import IPv4Address
from typing import Iterator, Self

from scapy.config import conf
from scapy.layers.inet import ICMP, IP
from scapy.sendrecv import sr1

NFT_LOGGER_NAME = "ctfroute.nft"


class EntityType(StrEnum):
    Team = "team"
    Router = "router"
    Gate = "gate"
    # throttle

    @property
    def state_attribute(self) -> str:
        return f"{self.value}s"


async def ping(ip: IPv4Address, retries=1, timeout=1) -> bool:  # noqa: ASYNC109
    src_interface, *_ = conf.route.route(str(ip))
    packet = IP(src=conf.ifaces[src_interface].ip, dst=str(ip)) / ICMP()
    reply = sr1(
        packet,
        retry=retries,
        timeout=timeout,
        verbose=False,
    )
    return reply is not None and reply.type == 0 and reply.src == str(ip)


def setup_logging():
    ctfoute_logger = logging.getLogger("ctfroute")
    ctftest_logger = logging.getLogger("ctftest")
    ctfoute_logger.setLevel(logging.DEBUG)
    ctftest_logger.setLevel(logging.DEBUG)

    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(levelname)s - %(message)s - %(name)s")
    handler.setFormatter(formatter)
    ctfoute_logger.addHandler(handler)
    ctftest_logger.addHandler(handler)

    # nft logger gets its own formatter
    nft_handler = logging.StreamHandler()
    nft_formatter = logging.Formatter("nft:\n%(message)s")
    nft_handler.setFormatter(nft_formatter)
    nft_logger = logging.getLogger(NFT_LOGGER_NAME)
    nft_logger.setLevel(logging.ERROR)
    # Don't propagate to prevent double log form ctfroute handler
    nft_logger.propagate = False
    nft_logger.addHandler(nft_handler)


class Backoff(Iterator[int]):
    def __init__(self, *, min_sec=1, max_sec=30, multiplier=2) -> None:
        self.min_sec = min_sec
        self.max_sec = max_sec
        self.multiplier = multiplier

        self.current = min_sec

    def __str__(self):
        return f"{self.current} seconds"

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> int:
        val = self.current
        self.current = min(self.current * self.multiplier, self.max_sec)
        return val

    def reset(self) -> None:
        self.current += self.min_sec
