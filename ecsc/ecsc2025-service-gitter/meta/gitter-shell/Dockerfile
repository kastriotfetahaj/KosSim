FROM ubuntu:noble-20240407.1@sha256:5b582c80ed6832665ffb6181ab4d3e5e70c30c2548fbcea1de8a0a51f161be8d AS build
ENV DEBIAN_FRONTEND=noninteractive
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    --mount=type=bind,source=./repro-sources-list.sh,target=/usr/local/bin/repro-sources-list.sh \
    repro-sources-list.sh && \
    apt-get update && \
    apt-get install -y clang git cmake libc++-dev libssl-dev libcurl4-openssl-dev nlohmann-json3-dev && \
    : "Clean up for improving reproducibility (optional)" && \
    rm -rf /var/log/* /var/cache/ldconfig/aux-cache

RUN mkdir -p /build/bin
COPY CMakeLists.txt /build
COPY src /build/src

WORKDIR /build/bin
RUN cmake -DCMAKE_BUILD_TYPE=Release .. && cmake --build . --parallel
RUN strip /build/bin/gitter-shell
