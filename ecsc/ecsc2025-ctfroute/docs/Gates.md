# Gates

Gates are used to block traffic within the games network. This is necessary to
control the games schedule, mitigate problems like runaway exploits / network loops from
pcap-shipping as well as "disciplinary" actions to punish misbehavior or generally 
prevent abusive / unfair behaviors.

ctfroute implements gates using nftables (nft) and is not trying to hide that
from you. Instead, it tries to help you write the right rules. More Details about 
the exact way nftables is used can be found in [./Nftables.md](./Nftables.md).

There are three mechanisms to deploy nft rules: ConnGates, RawGates and the 
`network.nft` setting.

`network.nft` simply deploys the specified nft commands onto all routers. As of writing,
`network.nft` can not be dynamically updated, but it will likely be in the future.

There is a designated table / chain for blocking traffic. RawGates allow you to simply
deploy a rule into that chain. A raw gate such as the one below will drop all
tcp-traffic destined for port 2000.

__Note:__ ctfoute does not make any guarantees about the order in which rules will be
inserted into the chain. If you insert "conflicting" raw rules whose effect depends
on the order of evaluation, the effects may vary. They may also vary between routers 
and, thus, also between teams.

```yaml
gates:
  - id: block-tcp-2000
    type: raw
    rule: tcp dport 2000 drop
```

ConnGates provide you with a shortcut to create rules for many common scenarios. They
allow you to craft blocking rules without having to mentally juggle things like
ip-address ranges of teams. Consider the example ConnGates below:

```yaml
gates:
  # Block traffic from any-team to other teams
  - id: block-others
    type: connection
    connSrc: any-team
    connDst: other-team
  
  # Team 1 may not connect to anyone, note that others still can connect to it
  - id: block-team-1
    type: connection
    connSrc: team-1
    connDst: other-team    
    
  # No team may connect to the vulnbox of another team on port 22
  - id: block-ssh
    type: connection
    connSrc: other-team
    connDst: any-vulnbox
    expression: tcp dport 22
```

The connSrc and connDst values allow you to reason about entities in the game, rather 
than ip addresses. On the other hand, `expression` gives you access to the full 
power of nft to create fine-grained rules. An empty expression blocks *all* traffic 
between the specified entities. 

## Supported connSrc and connDst values

Below is a description of the values that may be used in connSrc and connDst to target 
specific network entities.  

#### `known` and `unknown`

Any known ip address on the network, assigned to a team or a manually created 
network entity (see below). Unknown is the inverse of known.  

#### `any-team` and `any-vulnbox`

The Gate will affect all teams or all vulnboxes, details on that below.

#### `team-<id>` and `vulnbox-<id>`

As the names imply, these allow you to target specific teams or their vulnbox.

#### `same-team`

A meta entity that may only be used as connDst. The connSrc must be a specific team 
or any-team. The effect of any-team to same-team is the same as if you created a gate
team-X to same-team for every single team.

#### `other-team`

Similar to same-team, this is a meta entity. If used in connSrc, it refers to all 
teams that are not connDst, vice versa. Specifics are found below.

#### `game-<entity id>`

There are usually additional network entities in the game network, like for example 
the submitter. The `network.entities` setting is used to define entities that can 
then be referenced in gates and manually created rules.

## (in)valid combinations of connSrc and connDst and their semantics

Combinations that are marked with an ❌ where found to be ill-defined and will not be 
enforced, they will cause error logs from ctfoute, but should not crash it.

**Note: Keywords like `any-vulnbox` are shortened in the below table!**

| src / dst | known | unknown | any-vb | any-t | same-t | other-t | t-X | vb-X | g-X |
|-----------|-------|---------|--------|-------|--------|---------|-----|------|-----|
| known     |       |         |        |       | ❌      | ❌       |     |      |     |
| unknown   |       |         |        |       | ❌      | ❌       |     |      |     |
| any-vb    |       |         | 1)     |       |        |         |     |      |     |
| any-t     |       |         |        | 2)    |        | 3)      |     |      |     |
| same-t 4) | ❌     | ❌       | ❌      | ❌     | ❌ 5)   | ❌       | ❌   | ❌    | ❌   |
| other-t   | ❌     | ❌       |        | 3)    | ❌      | ❌       |     |      | ❌   |
| t-X       |       |         |        |       |        |         |     |      |     |
| vb-X      |       |         |        |       |        |         |     |      |     |
| g-X       |       |         |        |       | ❌      | ❌       |     |      |     |

### Explanations

#### 1) any-vulnbox to any-vulnbox

We can't prevent vulnboxes from accessing themselves, but we can generally block
vulnbox to vulnbox connections traversing the network. Note that this does not affect
connections between other hosts inside a teams network!

#### 2) any-team to any-team

This includes banning communication inside each teams network (at least over the vpn).
To ban communication only "between teams" use `any-team` to `other-team` instead.

#### 3) any-team ↔️ other-team

"any-team to other-team" and "other-team to any-team" are equivalent.

#### 4) same-team as src

Using "same-team" seems hard to reason about. We haven't found a use-case that would 
require it and simply disallowing it saves a lot of mental-gymnastics in the 
implementation.  

#### 5) same-team to same-team

Use any-team to same-team instead.
