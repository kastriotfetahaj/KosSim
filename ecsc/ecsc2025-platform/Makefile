UV_FLAGS ?= --inexact $(UV_FLAGS_EXTRA)
UV_RUN ?= env VIRTUAL_ENV=.venv uv run $(UV_FLAGS)
DOCKER_IMAGE ?= ci.attacking-lab.com/ad-platform/django

all: format lint mypy test

fix: format-fix lint-fix

format:
	@$(UV_RUN) ruff format --check

format-fix:
	@$(UV_RUN) ruff format

lint:
	@$(UV_RUN) ruff check

lint-fix:
	@$(UV_RUN) ruff check --fix

mypy:
	@$(UV_RUN) mypy

sync:
	uv sync $(UV_FLAGS)

build:
	docker build -t $(DOCKER_IMAGE) -f docker/Dockerfile .

push:
	docker push $(DOCKER_IMAGE)

.PHONY: all fix format format-fix lint lint-fix mypy sync
