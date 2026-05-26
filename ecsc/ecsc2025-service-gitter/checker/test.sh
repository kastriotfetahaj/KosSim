#!/bin/sh

export ENOCHECKER_TEST_SERVICE_ADDRESS=$(docker network inspect gitter_default | jq -r '.[].IPAM.Config[].Gateway')
export ENOCHECKER_TEST_SERVICE_PORT=9200
export ENOCHECKER_TEST_CHECKER_ADDRESS=$(docker network inspect gitter-checker | jq -r '.[].IPAM.Config[].Gateway')
export ENOCHECKER_TEST_CHECKER_PORT=8200

enochecker_test "$@"
