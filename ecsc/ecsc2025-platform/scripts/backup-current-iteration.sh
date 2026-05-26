#!/usr/bin/env bash

# USAGE: ./backup-current-iteration.sh 2024
# assuming there's a scoreboard at /static/scoreboard (!)

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
#REMOTE_STATIC_PATH=saarsec:/opt/saarctf-webpage/mainpage/static
REMOTE_STATIC_PATH=root@49.12.33.210:/opt/webpage-prod/docker/deployment/data/staticfiles

mkdir -p /dev/shm/saarctf
cd /dev/shm/saarctf

# Download all relevant files
wget -r -k -E --domains=ctf.saarland --reject-regex='.*[./]ova.*' --reject-regex='.*/vm/.*' -X 'static/old' https://ctf.saarland
scp -r "$REMOTE_STATIC_PATH/scoreboard/api" ctf.saarland/static/scoreboard/
scp -r "$REMOTE_STATIC_PATH/scoreboard/logos" ctf.saarland/static/scoreboard/

# store
mkdir -p "$DIR/mainpage/static/old/"
mv ctf.saarland "$DIR/mainpage/static/old/$1"

echo "[DONE] Stored in \"$DIR/mainpage/static/old/$1\""
