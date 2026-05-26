# Why no asyncio RAW_SOCKETS for capturing traffic in ctftest

Because python asyncio doesn't really support RAW_SOCKETS. Rumor has it that it would
theoretically work, but it is not supported and doesn't get tested.
See: https://github.com/python/cpython/issues/82466

# Why is ctfroute using python3-nftables?

The maintainers of nftables provide python bindings for `libnftables.so`, which are
distributed on debian as `python3-nftables`. They are not distributed via PyPI, because
the pyhon code needs to be aligned with the function signatures on the shared
library. The latter should of course be installed with the system package manager...

In principle, we wanted to avoid shenanigans such as this with ctfoute but in the
case of nftables loading the .so and passing nftables-rules to it really is the
better option. The reasons for that are as follows:

nftables lists as one of it's [Main Features](https://netfilter.org/projects/nftables/#main-features):

> Network-specific VM: the nft command line tool compiles the ruleset into the VM
> bytecode in netlink format, then it pushes this into the kernel via the nftables
> Netlink API. When retrieving the ruleset, the VM bytecode in netlink format is
> decompiled back to its original ruleset representation. So nft behaves both as
> compiler and decompiler.

That means we can't really avoid userspace interactions with nft, unless we were to
implement our own bytecode-(de)compiler for the netfilter-VM. Which we are obviously
not going to do...

The other option would be to use the legacy iptables interface, but,
well - it's legacy - and the netlink interface for it seems to be poorly documented.
Research mostly revealed other people looking for documentation which was typically
answered with "there is none, go read the iptables code."

# On anonymizing network metadata

All these mechanisms are skipped for team-internal traffic.

### NAT

All traffic from other teams is NATed from the gateway. If a packet can't be matched
by conntrack, it is dropped.

### TCP

We are NOPing all well known tcp options to prevent fingerprinting based on them.
See the NetfilterAnonymizationDriver code for details. NOPing options seems to generally
be safe, as long as we are doing it in all directions. The relevant RFCs are all
designed to be backwards-compatible. E.g. RFC1323 explicitly states that window scaling
can only be used if both ends of the connection include the relevant options in their
SYNs.

### IP TTL

We don't drop packets between routers by bumping their TTL above 1. This prevents
trace-routing the router topology. We cap TTL for packets going to teams at 42.

### IP dscp and ecn

Forced to 0.

### IP Options

We drop IP packets with options, this seems to be common practice even on the internet.
