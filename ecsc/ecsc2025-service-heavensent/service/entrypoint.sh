#!/bin/bash

# Generate key if necessary
if [ ! -f ./data/secret.bin ]; then
	echo "initializing secret.bin";
	dd if=/dev/random of=./data/secret.bin bs=16 count=1;
fi

# Do a dry run for first start
echo "dry run"
echo -n "" | ./run.sh &> /dev/null

# Start cron for the cleanup task
cron

# Run service
socat tcp-l:9501,reuseaddr,fork exec:./run.sh
