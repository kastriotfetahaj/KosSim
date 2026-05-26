from itertools import product

from ctfroute.defs import NET_ENT_MAX_LEN, NetRefKeyword, NetRefPrefix
from ctfroute.defs import NET_REF_PATTERN as PAT


def test_prefix_confusion():
    for kw, pf in product(NetRefKeyword, NetRefPrefix):
        assert not str(pf).startswith(str(kw))
        assert not str(kw).startswith(str(pf))


def test_net_ent_pattern():
    for kw in NetRefKeyword:
        assert PAT.match(kw) is not None
        assert PAT.match("a" + kw) is None

    for pf in NetRefPrefix:
        assert PAT.match(pf) is None
        assert PAT.match(pf + "a") is not None
        assert PAT.match(pf + "a" * NET_ENT_MAX_LEN) is not None
        assert PAT.match(pf + "a" * (NET_ENT_MAX_LEN + 1)) is None
