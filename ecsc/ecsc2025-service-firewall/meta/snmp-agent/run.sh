#!/bin/sh

mode="${1:-debug}"
DIR="$(dirname "$(readlink -f "$0")")"

export MIBS="${DIR}/../mib/ECSC2025-ATKLAB-FIREWALL-MIB.mib"
export SNMP_AUTH_COMMUNITY=firewall_auth
"${DIR}/build_${mode}/agent"
