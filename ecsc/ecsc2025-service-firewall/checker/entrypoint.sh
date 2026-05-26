#!/bin/bash
set -euxo pipefail

# Give the checker user access to /dev/net/tun
if ! find /dev/net -maxdepth 1 -name tun -perm '-o+rw' | grep -q '/dev/net/tun'; then
    chown root:checker /dev/net/tun
    chmod 0660 /dev/net/tun
fi

# Drop local connection priority to below the VPNs if a firewall mark is set.
# This is needed to loop user-to-user connections through the VPN connections.
# SAFETY: There should not be any routing entries to non-local addresses in the routing table.
for flag in -4 -6; do
    ip "${flag}" rule add preference 32765 from all lookup local
    ip "${flag}" rule del preference 0
    ip "${flag}" rule add preference 0 from all fwmark 0/0xffff lookup local
done

# TODO: Find a capsh solution for this (and the SUID binaries in the Dockerfile)
exec gosu checker uv run gunicorn -c checker/gunicorn.conf.py "${CHECKER_MODULE:-checker}:app"
