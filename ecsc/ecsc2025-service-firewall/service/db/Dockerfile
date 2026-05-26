FROM postgres:17.6-trixie@sha256:0f4f20021a065d114083d1b95d9fb89ad847cbc4c3cc9238417815c7df42350f

ADD --chmod=0755 --checksum=sha256:c125df9762b0c7233459087bb840c0e5dbfc4d9690ee227f1ed8994f4d51d2e0 \
    https://raw.githubusercontent.com/reproducible-containers/repro-sources-list.sh/v0.1.4/repro-sources-list.sh \
    /usr/local/bin/repro-sources-list.sh

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked --mount=type=cache,target=/var/lib/apt,sharing=locked \
    /usr/local/bin/repro-sources-list.sh && \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends --yes \
        postgresql-17-cron && \
    rm -f /usr/local/bin/repro-sources-list.sh

COPY --from=ecsc2025-service-firewall/routing /sbin/* /sbin/

COPY init.sql /docker-entrypoint-initdb.d/
COPY config/postgresql.conf config/pg_hba.conf /etc/postgres/

ENTRYPOINT ["/sbin/routing", "service"]
CMD ["/usr/local/bin/docker-entrypoint.sh", "-c", "config_file=/etc/postgres/postgresql.conf"]
