FROM python:3.13-slim-bookworm AS base

RUN apt update && apt install --no-install-recommends -y curl wireguard-tools iproute2 \
     tcpdump nftables python3-nftables iputils-ping iperf3 traceroute

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV VIRTUAL_ENV=/venv
RUN uv venv --python 3.13 "$VIRTUAL_ENV"
ENV PATH=$VIRTUAL_ENV/bin/:$PATH

WORKDIR /opt/ctfroute
COPY pyproject.toml .
COPY uv.lock .

RUN mkdir -p /opt/ctfroute/ctfroute/ctfroute
RUN mkdir -p /opt/ctfroute/ctfroute/ctfroute-k8s
RUN mkdir -p /opt/ctfroute/ctftest/ctftest
COPY ctfroute/pyproject.toml ctfroute/
COPY ctfroute-k8s/pyproject.toml ctfroute-k8s/
COPY ctftest/pyproject.toml ctftest/

FROM base AS ctfroute

RUN uv sync --no-install-package ctftest --compile-bytecode --active --no-install-workspace --frozen --exact
COPY ctfroute/ctfroute/ ctfroute/ctfroute/
COPY ctfroute-k8s/ctfroute_k8s/ ctfroute-k8s/ctfroute_k8s/
COPY ctfroute-k8s/README.md ctfroute-k8s/
RUN uv sync --no-install-package ctftest --compile-bytecode --active --frozen --exact
RUN ln -s /usr/lib/python3/dist-packages/nftables $VIRTUAL_ENV/lib/python3.13/site-packages/nftables

FROM base AS ctftest

ARG PYCHARM_PYDEV_VERSION=251.23536.40

RUN uv sync --compile-bytecode --no-install-workspace --active --frozen --exact
RUN uv pip install pydevd-pycharm==$PYCHARM_PYDEV_VERSION

COPY ctfroute/ctfroute/ ctfroute/ctfroute/
COPY ctfroute-k8s/ctfroute_k8s/ ctfroute-k8s/ctfroute_k8s/
COPY ctfroute-k8s/README.md ctfroute-k8s/
COPY ctfroute/tests/ ctfroute/tests/
COPY ctftest/ctftest/ ctftest/ctftest/
RUN uv sync --compile-bytecode --active --frozen --exact
RUN ln -s /usr/lib/python3/dist-packages/nftables $VIRTUAL_ENV/lib/python3.13/site-packages/nftables

# TODO: Currently needed for some unit tests
RUN mkdir docker
COPY docker/ctfroute.yml docker/
