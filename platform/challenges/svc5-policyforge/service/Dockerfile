FROM elixir:1.17-slim

WORKDIR /app
ENV MIX_ENV=prod
ENV MIX_HOME=/app/.mix
ENV HEX_HOME=/app/.hex
ENV REBAR_CACHE_DIR=/app/.cache/rebar3
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/* \
    && mix local.hex --force \
    && mix local.rebar --force \
    && adduser --disabled-password --gecos "" appuser
COPY svc5-policyforge/service/mix.exs ./mix.exs
COPY svc5-policyforge/service/config ./config
RUN mix deps.get --only prod
COPY svc5-policyforge/service/lib ./lib
COPY svc5-policyforge/service/priv ./priv
COPY svc5-policyforge/service/fixtures ./fixtures
RUN MIX_ENV=prod mix compile \
    && mkdir -p /var/lib/policyforge \
    && chown -R appuser:appuser /app /var/lib/policyforge

USER appuser

CMD ["mix", "run", "--no-halt"]
