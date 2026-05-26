# ALANA

Attacking Lab Assigned Numbers Administration

## Global

We generally use 10.0.0.0/8 addresses.

The core k8s cluster, used across all events uses the following networks:

```
cluster-cidr: 10.237.0.0/16
service-cidr: 10.238.0.0/16
```

## Per CTF

For any CTF, we choose a number `0 <= X <= 228`, `X % 2 == 0`.

We generally slice up a single `10.X.0.0/16` containing everything that needs to be
routable in the game. This may be referred to as the "game network".
For the team cloud networks (direct connection between routers and vulnboxes) we use
`10.<X+1>.0.0/16`. If a teams "game" network is `10.X.Y.0/24`, their cloud network is
`10.<X+1>.Y.0/24`.

Then there is two additional networks:

- `10.232.X.0/24` for the Router Dataplane
- `10.233.X.0/24` for the ctfroute Overlay

These two are deliberately entirely separate ip-ranges since they should not be
routable by participants of the game.

#### The Player Network

The Player network contains the /24 team networks, its CIDR is `10.X.0.0/17`,
accommodating 127 teams + NOP team. It is entirely virtual, implemented as wireguard
between routers and team devices.

### The Router Dataplane

The traffic between routers that serve as team endpoints is very performance-sensitive
and thus usually happens on an "internal" network provisioned by the cloud-provider.
In that network, the routers set up a wireguard mesh, so the addressing is not all
that important, but you should stick to `10.232.X.0/24` for ease of configuration.

This network is only accessible to routers and there should be no need for anyone to
poke around in there.

One of the routers is designated to serve as the gateway to the Infra Network:

### The Infra Network

The infra network hosts checkers, the submitter and the gameserver. Its CIDR is
`10.X.251.0/24`. Note that it is contained in the game network!

It's generally implemented as a cloud-provider network, with a router that is
connected to both the Router Dataplane and The Infra Network serving as a gateway
between them.

This router should always be `10.X.251.254`. The traffic from checkers to teams needs
to be routed appropriately by either deploying a route to all checker hosts or using
routing mechanisms from the cloud-provider. E.g. Hetzner conveniently allows setting
routes on their virtual networks which get implemented by the gateway.

### The ctfroute Overlay

To monitor routers and access them for traffic capture, ctfroute additionally sets
up an overlay network over all routers. This Network is implemented as additional
ip-addresses in the router mesh for the routers themselves. It's CIDR is
`10.233.X.0/24`. It is used by Prometheus - running in Kubernetes - to grab metrics
off of the routers and to access arkime running on the routers.

## Ports

The wireguard port used for ctfroute mesh network is `40.000 + X`. This avoids
collisions on kubernetes hosts that need to be connected to multiple CTFs.
The wireguard port for team vpn endpoints is usually in the 50.000 range, but we may
choose to randomize it in order to make it harder to scan vor team-vpn-endpoints.

## Connectivity Matrix

Empty => No connectivity
Y => Connectivity, vut always subject to firewalls
D => Depends, see footnotes
NAT => Yes, but with NAT

| From / To | Player | Infra | k8s  | ctfr Overlay | Dataplane | 
|-----------|--------|-------|------|--------------|-----------|
| Player    | Y      | Y     |      |              |           |
| Infra     | Y      | Y     | D 1) |              |           |
| k8s       |        |       | Y    | NAT 2)       |           |
| ctfr OL   |        |       | D 2) | Y            |           |
| Dataplane |        |       |      |              | Y         |

1) Infra hosts can optionally be joined into the cluster as agent nodes and then access
   services managed in k8s
2) We can deploy teamless routers onto kubernetes nodes, workloads on these nodes can
   then access the overlay network with NAT. Other hosts on the infra network could
   access kubernetes services if we set up port-forwards, but this is an unlikely
   use-case.

## Example

ECSC Staging, X = 32

| Network / Host | CIDR / Ip                              |
|----------------|----------------------------------------|
| ctfr Overlay   | 10.233.32.0/24                         |
| Dataplane      | 10.232.32.0/24                         |
| Player         | 10.32.0.0/17                           |
| Infra          | 10.32.251.0/24                         |
| Infra Router   | 10.32.251.254, 10.232.32.?, 2.233.32.? |
| Team Router    | 10.232.32.?, 2.233.32.?                |

### Hot Standbys

We can have "hot standbys" ready for team routers and the infra-router. I.e. the
hosts are already running and connected to ctfroute. To swap a bad team router, we
merely have to reconfigure ctf-route. To swap a bad infra-router we additionally
need to reconfigure the routing to team networks or simply give the `.254` ip to the
standby and turn off the bad one.

### Infra hosts running docker

To avoid routing collisions, we configure dockerd on infra hosts / vulnboxes as follows:

```json
// In /etc/docker/daemon.json
{
    "default-address-pools": [
        {
            "base": "172.16.0.0/11",
            "size": 24
        }
    ]
}
```
