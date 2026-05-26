"""
Wrapper for nftables import.

This is just a thin wrapper for importing python3-nftables that allows us to:
- Use the original python3-nftables as distributed alongside the libnftables.so.
- Fall back to a specific version of the python module that is included in the ctfroute
  source code.
"""

from logging import getLogger

LOGGER = getLogger(__name__)

try:
    from nftables import *  # noqa: F403
except ImportError:
    LOGGER.warning(
        "Failed to import python3-nftables, falling back to a version we have checked "
        "into ctfroute source code, this is not guaranteed to work!"
    )
    from ctfroute.drivers.netfilter.debian_nftables import *  # noqa: F403
