from ctfroute.defs import DEFAULT_MTU
from ctfroute.drivers.netfilter.driver import NetfilterAnonymizationDriver

ANON_TABLE = NetfilterAnonymizationDriver.TABLE


def test_anon_driver_flush(maybe_enter_namespace, nft):
    """Anon driver init must restore ruleset without duplicating rules."""
    nft.cmd(f"delete table {ANON_TABLE}")
    _ = NetfilterAnonymizationDriver(mtu=DEFAULT_MTU)

    code, out_first, err = nft.cmd(f"list table {ANON_TABLE}")
    assert code == 0, err

    _ = NetfilterAnonymizationDriver(mtu=DEFAULT_MTU)
    code, out, err = nft.cmd(f"list table {ANON_TABLE}")
    assert code == 0, err
    assert out == out_first
