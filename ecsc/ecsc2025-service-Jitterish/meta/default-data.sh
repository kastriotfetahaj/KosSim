#!/usr/bin/env bash

set -e

# workdir: service directory
# meta dir: /meta

if [ -d data/db-engine-data]; then
  echo "data directory already present"
  exit 0
fi

mkdir -p data
cp -r /meta/default-data data/db-engine-data
chown -r root:root data/db-engine-data
