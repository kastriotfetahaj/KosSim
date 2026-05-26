# How ctfroute uses nftables

ctfroute manipulates nftables in various ways. Many features are essentially a wrapper
around nft, and we are not really trying to hide that. The GateKeeper controller
essentially just helps you to write well-structured rules for typical use-cases, but
you can always fall back to deploying more or less "plain" nft commands.

For more information on how ctfroute interprets Gates, read [here](./Gates.md).

# Background

You should be generally familiar with nft. I recommend reading in the
[wiki](https://wiki.nftables.org/wiki-nftables/index.php/Main_Page).

A few important facts to be aware of are these:

nft "tables" are essentially namespaces for the entire list of "things" you can create
in nft. Chains, Sets, Rules, Counters, etc. That also means that you cannot access e.g.
sets defined in one table from another table.

`nft -a list ruleset` gives you a more-or-less complete dump of the rules and state.
This is very useful during debugging.

ConnGates are rendered to rules with counters and comments. The counter shows you how
much traffic a rule blocked and the comment allow you to easily map rules to gates,
without having to do the (de)referencing of rule handles.

```shell
$ nft -a list chain ctfr-gates gates
table ip ctfr-gates {
        chain gates { # handle 1
                type filter hook forward priority filter; policy accept;
                ip saddr @any-team ip daddr @t-1 ct direction original counter packets 0 bytes 0 drop comment "ConnGate src: any-team dst: team-1 id: shield-team-1" # handle 10
                ip saddr @t-2 ip daddr @t-1 ct direction original counter packets 0 bytes 0 drop comment "ConnGate src: team-2 dst: team-1 id: good" # handle 523
        }
}
```

The comments are **NOT** used by ctfroute to map rules to gates. It stores the rule
handles when creating rules instead.

ctfroute makes extensive use of [sets](https://wiki.nftables.org/wiki-nftables/index.php/Sets)
and [concatenations](https://wiki.nftables.org/wiki-nftables/index.php/Concatenations).

# Game entities and nft sets

As described in [the docs for Gates](./Gates.md) ConnGates are essentially a helper to
craft rules that target entities in the game, without having to reason about their
ip-addresses. To implement this, GateKeeper maintains sets that correspond to the
entities you can target with `gate.connSrc` and `gate.connDst`. This is also the reason
for the character limit on team and entity ids: GateKeeper translates them to nft sets
name which may not be longer than 16 chars.

| gate notation  | nft sets used     | Description                                     |
| -------------- | ----------------- | ----------------------------------------------- |
| known          | known             | Any address of a team or `network.entities`     |
| unknown        | known             | A negated lookup is used                        |
| any-vulnbox    | any-vulnbox       | Collection of teams[*].vulnbox                  |
| any-team       | any-team          | Collection of teams[*].network                  |
| team-1         | t-1               | Every team gets a set containing their network  |
| vulnbox-1      | t-1 & any-vulnbox | Both sets are checked for membership            |
| game-something | g-something       | Any item in `network.entities` gets its own set |

### Special case: `same-team` and `other-team`

GateKeeper maintains an additional set, called `same-team`, which contains nft 
concatenations (think python tuples) of each team's network. So there is an element
`(team.network, team.network)` for every team. This allows us to implement other-team
with a single rule using `ip saddr . ip daddr != @same-team`. Any traffic matching
this rule is originating form a different team than its destination. This is also
used for combinations of any-team and same-team. If the keyword same-team is used
together with a specific vulnbox-X or team-X, it resolves to `t-X` instead.

# Known tables and chains

This truncated excerpt from `nftables list ruleset` should give you an idea.

```shell
table ip ctfr-anon {
        chain mangle { # Used to anonymize packets
                ...
        }

        chain forward {
                type filter hook forward priority filter; policy accept;
                 # Only traffic destined for local teams will be mangled
                ip daddr 10.0.1.0/24 jump mangle
        }

        chain nat {
                type nat hook postrouting priority srcnat; policy accept;
                 # Only traffic destined for local teams will be NATed
                ip daddr 10.0.1.0/24 snat to 10.0.1.254
        }
}
table ip ctfr-gates {
        set same-team {
                typeof ip saddr . ip daddr
                flags interval
                elements = { 10.0.1.0/24 . 10.0.1.0/24,
                             ...
                             10.0.3.0/24 . 10.0.3.0/24 }
        }

        set known {
                type ipv4_addr
                flags interval
                elements = { 10.0.1.0/24, 10.0.2.0/24,
                             ...
                             10.0.255.0/24 }
        }

        set any-team {
                type ipv4_addr
                flags interval
                elements = { 10.0.1.0/24, 10.0.2.0/24,
                             ...
                             10.0.3.0/24 }
        }

        set any-vulnbox {
                type ipv4_addr
                flags interval
                elements = { 10.0.1.3, 10.0.2.3,
                             ...
                             10.0.3.3 }
        }

        set g-infra {
                type ipv4_addr
                flags interval
                elements = { 10.0.255.0/24 }
        }

        # sets for other network.entities ...

        set t-1 {
                type ipv4_addr
                flags interval
                elements = { 10.0.1.0/24 }
        }

        # sets for other teams ...

        chain gates { # Holds gates
                type filter hook forward priority filter; policy accept;

        }
}
```

# network.nft

CTFRoute state contains the field `network.nft` which is a string that will simply be
passed to `nft` when GateKeeper is initialized. This should allow for pretty much any
customization you should need.

If the nft provided is invalid, it will simply fail to apply and GateKeeper will keep
operating. It will not try to re-apply these rules. A log will be created to inform you
about the failure.

A few things to be aware of:

- You are responsible for making sure that the ruleset is idempotent. I.e. does not
  fail when applied a second time. The typical approach to this is to add, then flush
  / delete and then add your tables and chains again. A second initialization of
  GateKeeper on a host is always possible, since ctfroute might restart.

- The sets corresponding to keywords in ConnGate, such as any-team or any-vulnbox
  will be initialized by the time `network.nft` is applied, but this is not necessarily
  true for teams and sets created from `network.entities`, since they might be
  provisioned dynamically.

- Unless you are really confident that you know how ctfroute uses nftables, don't put
  your rules into a table prefixed with `ctfr-`.

# network.nft inspiration

Example used in real CTFs:
```shell
# Bypass gates for team orga
add rule ctfr-gates gates ip saddr @t-orga accept;
add rule ctfr-gates gates ip daddr @t-orga ct direction reply accept;

# Bypass gates for gameserver 
add rule ctfr-gates gates ip daddr 10.32.251.2 meta l4proto icmp accept; 
add rule ctfr-gates gates ip daddr 10.32.251.2 tcp dport { 80, 1337 } accept; 

# Make sure the static-forward chain exists ...
add chain ctfr-gates static-forward;
# So we can delete it ...
delete chain ctfr-gates static-forward;
# And add it again ...
add chain ctfr-gates static-forward {
  # prio 1 -> applied AFTER gates
  type filter hook forward priority 1; policy drop;

  # Accept all connections originating from orga / infra (checkers / gameserver)
  ip saddr @t-orga accept;
  ip daddr @t-orga ct direction reply accept;
  ip saddr @g-infra accept;
  ip daddr @g-infra ct direction reply accept;
  
  # Allow team-internal traffic
  ip saddr . ip daddr @same-team accept;
   
  # Drop anything that isn't tcp or icmp
  ip saddr @any-team meta l4proto != {tcp, icmp} counter drop;
  
  # Allow scoreboard and submitter;
  ip daddr 10.41.251.2 tcp dport { 80, 1337 } accept; 
 
  # If traffic is not within the same team, it must go to a vulnbox,
  # i.e.: Don't attack players machines  
  ip saddr . ip daddr != @same-team ip daddr @any-vulnbox accept;
  # Allow all replies from vulnboxes 
  ip saddr @any-vulnbox ct direction reply accept;
  
  # Policy is drop, count dropped traffic for debug
  counter;
}

# This chain is used to firewall off routers, note that these rules are deployed on any
# router, including those not hosting any teams. If you have additional services on 
# "routers" (e.g. elasticsearch accessed over the overlay) you need to allow traffic 
# appropriately. 
add chain ctfr-gates static-input;
delete chain ctfr-gates static-input;
add chain ctfr-gates static-input {
  type filter hook input priority filter; policy drop;
  iifname lo accept;
  
  # Accept traffic from "team" orga 
  ip saddr @t-orga accept;
  
  # Block other teams from accessing routers on data plane / overlay ips
  ip saddr @any-team ip daddr { 10.232.0.0/16 } counter drop;
  ip saddr @any-team ip daddr { 10.233.0.0/16 } counter drop;
  
  # Port range used for team wireguard vps
  udp dport 50000-50251 accept;
  
  # ICMP / ssh 
  meta l4proto { icmp, ipv6-icmp } accept;
  tcp dport { ssh } accept;
  
  # Allow dataplanne / overlay traffic
  ip saddr 10.232.0.0/16 accept;
  ip saddr 10.233.0.0/16 accept;
  # Allow outbound connections
  ct state vmap { established : accept, related : accept, invalid : drop }

  # Policy is drop, count dropped traffic for debug
  counter; 
}
```