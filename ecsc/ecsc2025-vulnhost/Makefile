all: format lint mypy test

fix: format-fix lint-fix

format:
	@uv run ruff format --check

format-fix:
	@uv run ruff format

lint:
	@uv run ruff check

lint-fix:
	@uv run ruff check --fix

mypy:
	@uv run mypy src/vulnhost/


.PHONY: all fix format format-fix lint lint-fix mypy
