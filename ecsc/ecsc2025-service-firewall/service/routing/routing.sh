#!/bin/bash
set -euo pipefail

case "${1:?Routing mode was not specified}" in
    service)
        # This routes the internal traffic directly, and the VPN/outbound traffic via the VPN.
        # It also enables proper TX checksumming (the Docker veth interfaces do not care, but
        # the VPN clients might).
        ip -4 route flush table main
        ip -6 route flush table main
        ip -4 route add 10.0.0.0/24 dev eth0 scope link
        ip -6 route add fd00:ec5c::/112 dev eth0 scope link
        ip -4 route add default via 10.0.0.1 dev eth0
        ip -6 route add default via fd00:ec5c::1 dev eth0
        ethtool --offload eth0 tx-checksumming off >&-
        ;;
    router)
        # Here, we can't rely on a default route, but we still need to route VPN-bound traffic via eth0.
        ip -4 route flush dev eth0
        ip -6 route flush dev eth0
        ip -4 route add 10.0.0.0/24 dev eth0 scope link
        ip -6 route add fd00:ec5c::/112 dev eth0 scope link
        ip -4 route add 10.0.0.0/8 via 10.0.0.254 dev eth0
        ip -6 route add fd00:ec5c::/80 via fd00:ec5c::fe dev eth0
        ip neigh add 10.0.0.254 dev eth0 lladdr 00:00:00:00:00:00 nud permanent
        ip neigh add fd00:ec5c::fe dev eth0 lladdr 00:00:00:00:00:00 nud permanent
        ethtool --offload eth0 tx-checksumming off >&-
        ;;
    *)
        echo "Unknown routing mode: ${1}"
        exit 1
        ;;
esac
shift

exec capsh --drop=cap_net_admin --no-new-privs -- -c 'exec "$@"' -- "$@"
