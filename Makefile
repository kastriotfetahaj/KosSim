SHELL := /bin/bash
COMPOSE ?= docker compose
BOOTSTRAP_PYTHON ?= $(shell if command -v python3.12 >/dev/null 2>&1; then command -v python3.12; elif command -v python3.11 >/dev/null 2>&1; then command -v python3.11; elif command -v python3.10 >/dev/null 2>&1; then command -v python3.10; else command -v python3; fi)
VENV ?= .venv-tests
PYTHON ?= $(VENV)/bin/python
ENV_FILE ?= .env.example

.PHONY: setup python-deps verify dev build test checkers exploits patches reset lint validate smoke smoke-docker web-build ci compose-config build-services

$(VENV)/.deps: requirements-dev.txt platform/control/requirements.txt
	$(BOOTSTRAP_PYTHON) -m venv $(VENV)
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements-dev.txt
	touch $(VENV)/.deps

python-deps: $(VENV)/.deps

setup: python-deps
	npm ci --prefix platform/control/web

verify: validate compose-config test web-build smoke

dev:
	$(COMPOSE) --env-file $(ENV_FILE) up --build

build: compose-config build-services

build-services:
	$(COMPOSE) --env-file $(ENV_FILE) build team1-svc1 team1-svc2 team1-svc3 team1-svc4 team1-svc5

compose-config:
	$(COMPOSE) --env-file $(ENV_FILE) config >/dev/null

test: python-deps
	$(PYTHON) -m pytest tests

web-build:
	npm ci --prefix platform/control/web
	npm run build --prefix platform/control/web

validate: python-deps
	$(PYTHON) scripts/validate_platform.py

smoke: python-deps
	$(PYTHON) scripts/smoke_platform.py

smoke-docker: python-deps
	$(PYTHON) scripts/smoke_platform.py --docker

checkers: python-deps
	$(PYTHON) organizer/ci/run_checkers.py

exploits: python-deps
	$(PYTHON) organizer/ci/run_exploits.py

patches: python-deps
	$(PYTHON) organizer/ci/validate_patches.py

reset:
	$(COMPOSE) --env-file $(ENV_FILE) down -v --remove-orphans

lint: validate
	$(PYTHON) -m pytest tests/unit/test_challenge_pack_contract.py

ci: verify checkers exploits patches
