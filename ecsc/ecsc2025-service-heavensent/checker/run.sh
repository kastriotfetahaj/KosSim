#!/bin/sh

export ENOCHECKER_TEST_SERVICE_ADDRESS=$(docker network inspect heavensent-checker | jq -r '.[].IPAM.Config[].Gateway')
# export ENOCHECKER_TEST_SERVICE_ADDRESS=141.23.191.141
export ENOCHECKER_TEST_SERVICE_PORT=9500
export ENOCHECKER_TEST_CHECKER_ADDRESS=$(docker network inspect heavensent-checker | jq -r '.[].IPAM.Config[].Gateway')
export ENOCHECKER_TEST_CHECKER_PORT=8500

echo $ENOCHECKER_TEST_SERVICE_ADDRESS
echo $ENOCHECKER_TEST_CHECKER_ADDRESS

enochecker_test "$@"
