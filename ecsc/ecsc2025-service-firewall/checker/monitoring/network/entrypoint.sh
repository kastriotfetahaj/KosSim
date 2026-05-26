#!/bin/bash
set -euxo pipefail
ip -tshort monitor > /logs/ip-monitor.log &
tcpdump -i any -w /logs/traffic.pcap &
wait -n
