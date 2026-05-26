#!/bin/sh

docker compose -f service/docker-compose.yml -f meta/docker-compose.override.yml \
	run ssh-build
