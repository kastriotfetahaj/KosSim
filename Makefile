SHELL := /bin/bash
COMPOSE ?= docker compose
BOOTSTRAP_PYTHON ?= $(shell if command -v python3.12 >/dev/null 2>&1; then command -v python3.12; elif command -v python3.11 >/dev/null 2>&1; then command -v python3.11; elif command -v python3.10 >/dev/null 2>&1; then command -v python3.10; else command -v python3; fi)
PYTHON ?= $(shell if [ -x .venv-tests/bin/python ]; then echo .venv-tests/bin/python; else echo $(BOOTSTRAP_PYTHON); fi)
ENV_FILE ?= .env.example

.PHONY: setup verify dev build test checkers exploits patches reset lint validate smoke smoke-docker web-build ci compose-config build-services

setup:
	rm -rf .venv-tests
	$(BOOTSTRAP_PYTHON) -m venv .venv-tests
	.venv-tests/bin/python -m pip install --upgrade pip
	.venv-tests/bin/python -m pip install -r requirements-dev.txt
	npm ci --prefix platform/control/web

verify: validate compose-config test web-build smoke

dev:
	$(COMPOSE) --env-file $(ENV_FILE) up --build

build: compose-config build-services

build-services:
	$(COMPOSE) --env-file $(ENV_FILE) build team1-svc1 team1-svc2 team1-svc3 team1-svc4 team1-svc5

compose-config:
	$(COMPOSE) --env-file $(ENV_FILE) config >/dev/null

test:
	$(PYTHON) -m pytest tests

web-build:
	npm ci --prefix platform/control/web
	npm run build --prefix platform/control/web

validate:
	$(PYTHON) scripts/validate_platform.py

smoke:
	$(PYTHON) scripts/smoke_platform.py

smoke-docker:
	$(PYTHON) scripts/smoke_platform.py --docker

checkers:
	$(PYTHON) organizer/ci/run_checkers.py

exploits:
	$(PYTHON) organizer/ci/run_exploits.py

patches:
	$(PYTHON) organizer/ci/validate_patches.py

reset:
	$(COMPOSE) --env-file $(ENV_FILE) down -v --remove-orphans

lint: validate
	$(PYTHON) -m pytest tests/unit/test_challenge_pack_contract.py

ci: verify checkers exploits patches
