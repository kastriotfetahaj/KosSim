# ctfroute

## For Developers

All sample commands are run in `<git-root>/ctfroute`.

### Install dependencies

```sh
uv sync
```

### Tests

We have integration and unit tests. You may consider it heretical, but we run both with
pytest.

```sh
pytest # Unit tests
# in order to run the integration tests, the docker compose setup must be running!
pytest  --integration # Integration tests
```

### type checking

```sh
mypy
```

### linting / formatting

```sh
ruff format
ruff check
```
