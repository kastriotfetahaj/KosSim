SHELL := /bin/bash
COMPOSE ?= docker compose
PYTHON ?= $(shell if [ -x .venv-tests/bin/python ]; then echo .venv-tests/bin/python; else command -v python3; fi)
ENV_FILE ?= .env.example

.PHONY: dev build test checkers exploits patches reset lint ci compose-config build-services

dev:
	$(COMPOSE) --env-file $(ENV_FILE) up --build

build: compose-config build-services

build-services:
	$(COMPOSE) --env-file $(ENV_FILE) build team1-svc1 team1-svc2 team1-svc3 team1-svc4 team1-svc5

compose-config:
	$(COMPOSE) --env-file $(ENV_FILE) config >/dev/null

test:
	$(PYTHON) -m pytest tests

checkers:
	$(PYTHON) organizer/ci/run_checkers.py

exploits:
	$(PYTHON) organizer/ci/run_exploits.py

patches:
	$(PYTHON) organizer/ci/validate_patches.py

reset:
	$(COMPOSE) --env-file $(ENV_FILE) down -v --remove-orphans

lint:
	$(PYTHON) -m pytest tests/unit/test_challenge_pack_contract.py

ci: compose-config test checkers exploits patches
