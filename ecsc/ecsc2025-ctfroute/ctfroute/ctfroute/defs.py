import re
from enum import StrEnum

# Standard 1500 ethernet - 80 bytes: IPv6, UDP, WireGuard
DEFAULT_MTU = 1420

# https://www.rfc-editor.org/rfc/rfc6691#section-2
MSS_DIFF = 40

# Some ids are used in interface names, we want to keep those ergonomic.
IFNAME_PATTERN = re.compile(r"^[a-zA-Z0-9-_]+$")

# We are using netfilter named sets to refer to network entities (e.g. teams) in rules.
# Names of sets may at most be 16 chars long. To avoid collisions, we prefix them based
# on their origin.
# Furthermore, we use team ids for the names of their wireguard interfaces.
NFT_SET_NAME_MAX_LEN = 16
IFNAME_MAX_LEN = 15
NFT_SET_PREFIX_MAX_LEN = IFNAME_PREFIX_MAX_LEN = 3

NET_ENT_MAX_LEN = IFNAME_MAX_LEN - IFNAME_PREFIX_MAX_LEN
assert NET_ENT_MAX_LEN <= (NFT_SET_NAME_MAX_LEN - NFT_SET_PREFIX_MAX_LEN)

TEAM_IFNAME_PREFIX = "tt-"
assert len(TEAM_IFNAME_PREFIX) <= IFNAME_PREFIX_MAX_LEN
assert IFNAME_PATTERN.match(TEAM_IFNAME_PREFIX)


class NFTSetPrefix(StrEnum):
    team = "t-"
    game = "g-"


for pf in NFTSetPrefix:
    assert len(pf) < NFT_SET_PREFIX_MAX_LEN


# Special magic values for network entities in gate definitions
class NetRefKeyword(StrEnum):
    known = "known"  # Any known entity
    unknown = "unknown"  # Ip addresses not assigned to anything
    any_vulnbox = "any-vulnbox"
    any_team = "any-team"
    # May be used in conjunction with any-team
    same_team = "same-team"
    other_team = "other-team"
    # TODO These might be handy for custom rules
    # local_teams = "local-teams"
    # remote_teams = "local-teams"


for kw in NetRefKeyword:
    # We use these as nft set names!
    assert len(kw) < NFT_SET_NAME_MAX_LEN


# Prefixes for net entities in gates. We shorten the prefixes before submitting them to
# nft - see NFTSetPrefix
class NetRefPrefix(StrEnum):
    team = "team-"  # Teams entire network
    vulnbox = "vulnbox-"  # Vulnbox of team
    game = "game-"  # Custom net entities


# A Net entity reference is either one of the keywords or a prefix followed by an id
_KWORDS = "|".join(NetRefKeyword)
_PREFIXES = "|".join(NetRefPrefix)
NET_REF_PATTERN = re.compile(rf"^{_KWORDS}|(({_PREFIXES})(.{{1,{NET_ENT_MAX_LEN}}}))$")
