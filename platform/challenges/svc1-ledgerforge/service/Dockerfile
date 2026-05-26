FROM rust:1.85-bookworm AS builder

WORKDIR /build
COPY svc1-ledgerforge/service/Cargo.toml ./Cargo.toml
COPY svc1-ledgerforge/service/src ./src
RUN cargo build --release

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -u 10001 appuser
WORKDIR /app
COPY --from=builder /build/target/release/ledgerforge /app/ledgerforge
COPY svc1-ledgerforge/service/static /app/static
RUN mkdir -p /var/lib/ledgerforge \
    && chown -R appuser:appuser /app /var/lib/ledgerforge
USER appuser

ENV LEDGERFORGE_DATA_DIR=/var/lib/ledgerforge \
    PORT=8080

EXPOSE 8080

CMD ["/app/ledgerforge"]
