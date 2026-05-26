# Builds are incremental, i.e., code changes should compile pretty fast.
# To wipe the build caches and do a fresh rebuild of everything: docker builder prune --filter type=exec.cachemount


# 0. Compilation/runtime basics: working C/C++ compiler with support for C++ modules
FROM debian:trixie@sha256:833c135acfe9521d7a0035a296076f98c182c542a2b6b5a0fd7063d355d696be AS basis
ENV DEBIAN_FRONTEND=noninteractive
ADD https://raw.githubusercontent.com/reproducible-containers/repro-sources-list.sh/39fbf150e3a5062d4c6b9a241f25af133e7cb6f0/repro-sources-list.sh /var/lib/repro-sources-list.sh
RUN \
    --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    bash /var/lib/repro-sources-list.sh && \
    apt-get update && \
    apt-get install -y clang-18 clang-tools-18 lld-18 nano htop wget curl && \
    apt-get clean && \
    update-alternatives --install /usr/bin/cc cc /usr/bin/clang-18 100 && \
    update-alternatives --install /usr/bin/c++ c++ /usr/bin/clang++-18 100 && \
    update-alternatives --install /usr/bin/ld ld /usr/bin/ld.lld-18 100


# 1. Build C++ component (compiler)
FROM basis AS builder-cpp
RUN apt-get update && \
    apt-get install -y --no-install-recommends cmake default-jre-headless git ninja-build && \
    apt-get clean && \
    mkdir -p /src /build /output

COPY jit /src/

RUN --mount=type=cache,id=cache-cpp,target=/build,sharing=locked \
    cd /build && \
    cmake ../src -G Ninja -DCMAKE_BUILD_TYPE=MinSizeRel && \
    ninja -j 2 jit && \
    cp jit *.so /output/


# 2. Build Rust
FROM rust:trixie@sha256:1ca9500fa119fe67cc67de86fe0ce8c77d747bfb541d227cd6eca463d29cc454 AS builder-rust
COPY dbengine /src/dbengine
COPY interface /src/interface
RUN --mount=type=cache,id=cache-rust-engine,target=/src/dbengine/target,sharing=locked \
    --mount=type=cache,id=cache-rust-interface,target=/src/interface/target,sharing=locked \
    --mount=type=cache,target=/usr/local/cargo/git/db \
    --mount=type=cache,target=/usr/local/cargo/registry/ \
    mkdir -p /output && \
    cd /src/dbengine && \
    cargo build -j 2 --release && \
    cp target/release/dbengine /output/


# 3. Build runtime container
FROM basis AS runtime
# install assembler + linker
RUN mkdir -p /app/compiler /app/dbengine

COPY --from=builder-cpp /output/* /app/compiler/
COPY --from=builder-rust /output/* /app/dbengine/

WORKDIR /app/dbengine
STOPSIGNAL SIGINT

CMD ["/app/dbengine/dbengine"]
