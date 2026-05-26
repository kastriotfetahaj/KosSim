# Builds are incremental, i.e., code changes should compile pretty fast.
# To wipe the build caches and do a fresh rebuild of everything: docker builder prune --filter type=exec.cachemount


# 1. Build Rust Application
FROM rust:trixie@sha256:1ca9500fa119fe67cc67de86fe0ce8c77d747bfb541d227cd6eca463d29cc454 AS builder-rust
COPY interface /src/interface
COPY website/Cargo.* /src/website/
COPY website/src /src/website/src

RUN --mount=type=cache,id=cache-rust-website,target=/src/website/target,sharing=locked \
    --mount=type=cache,id=cache-rust-interface,target=/src/interface/target,sharing=locked \
    --mount=type=cache,target=/usr/local/cargo/git/db \
    --mount=type=cache,target=/usr/local/cargo/registry/ \
    mkdir output && \
    cd /src/website && \
    cargo build -j 2 --release && \
    cp target/release/website /output/


# 2. Build runtime container
FROM debian:trixie@sha256:833c135acfe9521d7a0035a296076f98c182c542a2b6b5a0fd7063d355d696be AS runtime

COPY --from=builder-rust /output/website /app/website/
COPY website/queries /app/website/queries
COPY website/static /app/website/static
COPY website/templates /app/website/templates
COPY website/Rocket.toml /app/website/

WORKDIR /app/website

ENV ROCKET_ADDRESS=0.0.0.0
ENV ROCKET_PORT=9400

CMD ["/app/website/website"]
