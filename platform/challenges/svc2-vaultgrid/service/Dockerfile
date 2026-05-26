FROM debian:bookworm AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential make libsqlite3-dev libcrypt-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY svc2-vaultgrid/service/Makefile ./Makefile
COPY svc2-vaultgrid/service/src ./src
RUN make

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl libsqlite3-0 libcrypt1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -u 10002 appuser \
    && mkdir -p /var/lib/vaultgrid \
    && chown -R appuser:appuser /var/lib/vaultgrid
WORKDIR /app
COPY --from=builder /build/vaultgrid /app/vaultgrid
COPY svc2-vaultgrid/service/static /app/static
USER appuser
ENV VAULTGRID_DATA_DIR=/var/lib/vaultgrid \
    VAULTGRID_CRYPT_HOST=vaultgrid-crypt \
    VAULTGRID_CRYPT_PORT=4102 \
    VAULTGRID_FEED_HOST=vaultgrid-feed \
    VAULTGRID_FEED_PORT=4103
EXPOSE 8080
CMD ["/app/vaultgrid"]
