#!/bin/sh
export MIBDIRS="+$(realpath ../../../service/firewall/snmp/mib)"
export MIBS="$(realpath ../../../service/firewall/snmp/mib/ECSC2025-ATKLAB-FIREWALL-MIB.mib)"
export SNMP_AUTH_COMMUNITY=foo
export LD_LIBRARY_PATH=.

exec afl-fuzz -i seed -o output/ -- ../build_fuzzing/agent
