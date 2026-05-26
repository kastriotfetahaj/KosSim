FROM debian:trixie-20250908-slim@sha256:c2880112cc5c61e1200c26f106e4123627b49726375eb5846313da9cca117337

ADD --chmod=0755 --checksum=sha256:c125df9762b0c7233459087bb840c0e5dbfc4d9690ee227f1ed8994f4d51d2e0 \
    https://raw.githubusercontent.com/reproducible-containers/repro-sources-list.sh/v0.1.4/repro-sources-list.sh \
    /usr/local/bin/repro-sources-list.sh

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked --mount=type=cache,target=/var/lib/apt,sharing=locked \
    /usr/local/bin/repro-sources-list.sh && \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends --yes \
        openssl python3 python3-pip && \
    rm -f /usr/local/bin/repro-sources-list.sh

RUN pip install --break-system-packages --root-user-action=ignore "uv~=0.8.17"

WORKDIR /srv/
RUN --mount=type=bind,source=pyproject.toml,target=/srv/pyproject.toml \
    --mount=type=bind,source=uv.lock,target=/srv/uv.lock \
    uv sync --exact --frozen

COPY --from=ecsc2025-service-firewall/routing /sbin/* /sbin/

COPY --chown=root:root --chmod=0400 ftpd.py /srv/ftpd.py
COPY --chown=root:root --chmod=0400 ftpd.toml /etc/ftpd.toml

ENTRYPOINT ["/sbin/routing", "service"]
CMD ["/usr/local/bin/uv", "run", "ftpd.py"]
