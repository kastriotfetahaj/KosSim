#!/bin/sh
set -eux
cd /

# Install dependencies
apk add bash coreutils git python3 py3-pip

# Install checker test dependencies
# Unfortunately the PAT trick does not work out of the box for enochecker_cli, since that has ssh submodules
requirements="$(mktemp)"
grep -v '^enochecker-cli' /host/checker/tests/requirements.txt > "${requirements}"
/host/checker/with-pat.sh pip install --break-system-packages -r "${requirements}"
rm -f "${requirements}"

dependency="$(grep '^enochecker-cli' /host/checker/tests/requirements.txt | sed 's/^[^@]*@ *//')"
repository="$(echo "${dependency}" | sed 's/^git+\([^@]*\)@.*$/\1/')"
ref="$(echo "${dependency}" | sed 's/^.*@//')"

/host/checker/with-pat.sh git clone "${repository}" enochecker-cli

cd /enochecker-cli
git checkout "${ref}"
pip install --break-system-packages -e .

# Get going
cd /host/
./build.sh

cd /host/service/
docker compose up --build --wait

cd /host/checker/
docker compose up --build --wait

echo 'We are ready.'
