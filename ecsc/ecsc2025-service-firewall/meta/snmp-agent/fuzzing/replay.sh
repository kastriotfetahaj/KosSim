#!/bin/sh
INPUT="$1"

export MIBDIRS="+$(realpath ../../../service/firewall/snmp/mib)"
export MIBS="$(realpath ../../../service/firewall/snmp/mib/ECSC2025-ATKLAB-FIREWALL-MIB.mib)"
export SNMP_AUTH_COMMUNITY=foo
export LD_LIBRARY_PATH=.

../build_fuzzing/agent < "$INPUT"
