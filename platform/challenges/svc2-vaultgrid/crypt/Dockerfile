FROM rust:1.85-bookworm AS builder
WORKDIR /build
COPY svc2-vaultgrid/crypt/Cargo.toml ./Cargo.toml
COPY svc2-vaultgrid/crypt/src ./src
RUN cargo build --release

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -u 10002 cryptuser \
    && mkdir -p /var/lib/vaultgrid-crypt \
    && chown -R cryptuser:cryptuser /var/lib/vaultgrid-crypt
WORKDIR /app
COPY --from=builder /build/target/release/vaultgrid-crypt /app/vaultgrid-crypt
USER cryptuser
ENV VAULTGRID_CRYPT_DATA_DIR=/var/lib/vaultgrid-crypt
EXPOSE 4102
CMD ["/app/vaultgrid-crypt"]
