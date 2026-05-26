#!/bin/bash

# Download and retag GNU Radio image
docker pull ci.attacking-lab.com/ecsc2025/service-heavensent/gnuradio
docker tag ci.attacking-lab.com/ecsc2025/service-heavensent/gnuradio attackinglab/heavensent-gnuradio
docker save attackinglab/heavensent-gnuradio -o service/images/heavensent-gnuradio.tar
docker save attackinglab/heavensent-gnuradio -o checker/images/heavensent-gnuradio.tar

# Build from source
echo "Building service using AngelScript source code"
cd service
rm ../meta/as_src/heavensent.bin
ln -s ../meta/docker-compose.source.yml docker-compose.override.yml
docker compose up --build --force-recreate -d

# Copy out bytecode
echo -n "Waiting for bytecode file to be created."
num_retries=0
max_retries=30
until [ -f ../meta/as_src/heavensent.bin ]
do
	[[ $num_retries -eq $max_retries ]] && echo "Timed out waiting for bytecode file" && exit 1
	echo -n "."
	sleep 1
	num_retries=$((num_retries+1))
done
cp ../meta/as_src/heavensent.bin ./as_bin/
echo "done!"

# Cleanup
echo "Cleaning up"
docker compose down
rm docker-compose.override.yml
rm -r data/*
