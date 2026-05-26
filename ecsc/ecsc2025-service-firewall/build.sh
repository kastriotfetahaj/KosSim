#!/bin/bash
set -euo pipefail

if [ -f service/firewall/snmp/agent ]; then
    echo "Current agent:"
    sha256sum service/firewall/snmp/agent
fi

# This builds the SNMP agent during deployment via the CI, and places it in the service directory.
pushd meta/snmp-agent
echo "Starting SNMP agent build"
docker compose -f docker-compose.build.yml run --rm --build agent-build

popd
echo "Finished clean build:"
sha256sum service/firewall/snmp/agent
