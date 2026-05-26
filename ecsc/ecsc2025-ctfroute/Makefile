UV_FLAGS ?= --inexact $(UV_FLAGS_EXTRA)
UV_RUN ?= env VIRTUAL_ENV=.venv uv run $(UV_FLAGS)

all: format lint mypy test

fix: format-fix lint-fix

format:
	$(UV_RUN) ruff format --check

format-fix:
	$(UV_RUN) ruff format

lint:
	$(UV_RUN) ruff check

lint-fix:
	$(UV_RUN) ruff check --fix

mypy:
	$(UV_RUN) mypy

test: ctfroute-test

ctfroute-test:
	cd ctfroute && \
		($(UV_RUN) coverage run -m pytest -W error -v $(TEST_FLAGS) && \
		$(UV_RUN) coverage report -m)

sync:
	uv sync $(UV_FLAGS)

build:
	uv build

.PHONY: all fix format format-fix lint lint-fix mypy test ctfroute-test sync build
