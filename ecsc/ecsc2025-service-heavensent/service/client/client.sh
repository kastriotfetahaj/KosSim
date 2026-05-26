#!/bin/bash

IMAGE_TAR="../images/heavensent-gnuradio.tar"

TAR_HASH=$(tar -xOf $IMAGE_TAR manifest.json | grep -Eo '"Config":"blobs/sha256/[a-f0-9]+"' | cut -d'"' -f4 | cut -d'/' -f3)
LOCAL_HASH=$(docker images --no-trunc attackinglab/heavensent-gnuradio | tail -n1 | cut -d':' -f2 | cut -d' ' -f1)

if [[ -n "$TAR_HASH" && "$TAR_HASH" != "$LOCAL_HASH" ]]; then
    echo "Different tar image found. Loading that one ..."
    docker load -i $IMAGE_TAR
elif [[ -z "$TAR_HASH" ]]; then
    echo "WARN: No hash for the tar file found."
fi

echo "Running..."
docker compose run --build --remove-orphans heavensent-client
