ARG PROFILE=release
ARG AGENT_SOURCE=agent-prebuilt

# Build firewalld
FROM rust:1.90.0-slim-trixie@sha256:40d4ee109c7e740b3a242f20cc3b5790af9c725828b86a458765f192391a6a4a AS firewalld-builder

RUN cargo new --bin firewalld
WORKDIR /firewalld

COPY firewalld/Cargo.toml /firewalld/Cargo.toml
COPY firewalld/Cargo.lock /firewalld/Cargo.lock

ARG PROFILE
ENV RUSTFLAGS="-C target-cpu=x86-64-v2 -C opt_level=3"
RUN cargo build --profile ${PROFILE} && \
    rm -rf /firewalld/src /firewalld/target/${PROFILE}/deps/firewalld*

COPY firewalld/src /firewalld/src
RUN cargo build --profile ${PROFILE}



# By default, use the prebuilt SNMP agent
FROM scratch AS agent-prebuilt

COPY snmp/agent /agent

# (This needs a staging copy, per moby/moby #34482)
FROM ${AGENT_SOURCE} AS agent-source



# Build the final container image
FROM debian:trixie-20250908-slim@sha256:c2880112cc5c61e1200c26f106e4123627b49726375eb5846313da9cca117337

ADD --chmod=0755 --checksum=sha256:c125df9762b0c7233459087bb840c0e5dbfc4d9690ee227f1ed8994f4d51d2e0 \
    https://raw.githubusercontent.com/reproducible-containers/repro-sources-list.sh/v0.1.4/repro-sources-list.sh \
    /usr/local/bin/repro-sources-list.sh

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked --mount=type=cache,target=/var/lib/apt,sharing=locked \
    /usr/local/bin/repro-sources-list.sh && \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends --yes \
        libsnmp40t64 patch python3 python3-pip supervisor && \
    rm -f /usr/local/bin/repro-sources-list.sh

RUN pip install --break-system-packages --root-user-action=ignore "uv~=0.8.17"

WORKDIR /var/www/
RUN --mount=type=bind,source=frontend/uv.lock,target=/var/www/uv.lock \
    --mount=type=bind,source=frontend/pyproject.toml,target=/var/www/pyproject.toml \
    --mount=type=bind,source=frontend/pysnmp.patch,target=/pysnmp.patch \
    uv sync --exact --frozen && \
    patch -p1 .venv/lib/python3.13/site-packages/pysnmp/hlapi/v1arch/asyncio/cmdgen.py /pysnmp.patch
WORKDIR /

COPY --from=ecsc2025-service-firewall/routing /sbin/* /sbin/

RUN useradd -u 1161 -M snmp

# Copy firewalld
ARG PROFILE
COPY --from=firewalld-builder /firewalld/target/${PROFILE}/firewalld /bin/firewalld

# Copy frontend
COPY --chmod=0555 frontend/static/ /var/www/static/
COPY --chmod=0555 frontend/html/ /var/www/html/
COPY --chmod=0555 frontend/manager/ /var/www/manager/
COPY --chmod=0555 frontend/app.py frontend/config.py frontend/gunicorn.conf.py /var/www/

# Copy agent
COPY --chmod=0555 snmp/mib/ /usr/share/mib/
COPY --from=agent-source /agent /bin/agent

# Copy configuration
RUN mkdir --mode=0555 /etc/firewall/
COPY --chmod=0400 frontend/frontend.toml /etc/firewall/frontend.toml
COPY --chmod=0444 firewalld/filter /etc/firewall/filter

# supervisord will run everything
COPY --chmod=0400 supervisord.conf /etc/supervisord.conf

ENTRYPOINT ["/sbin/routing", "router"]
CMD ["/bin/supervisord", "-c", "/etc/supervisord.conf"]
