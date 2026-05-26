ARG SNMP_PROFILE=release
FROM debian:trixie-20250908-slim@sha256:c2880112cc5c61e1200c26f106e4123627b49726375eb5846313da9cca117337 AS snmp-builder

ADD --chmod=0755 --checksum=sha256:c125df9762b0c7233459087bb840c0e5dbfc4d9690ee227f1ed8994f4d51d2e0 \
    https://raw.githubusercontent.com/reproducible-containers/repro-sources-list.sh/v0.1.4/repro-sources-list.sh \
    /usr/local/bin/repro-sources-list.sh

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked --mount=type=cache,target=/var/lib/apt,sharing=locked \
    /usr/local/bin/repro-sources-list.sh && \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends --yes \
        build-essential clang libsnmp-dev python3 python3-pip python3-wheel && \
    rm -f /usr/local/bin/repro-sources-list.sh

RUN --mount=source=obfuscator/requirements.txt,target=/requirements.txt \
    pip3 install -r /requirements.txt --break-system-packages

COPY --chmod=0555 obfuscator/qobf.py /bin/qobf

COPY src /build/src
COPY Makefile /build
WORKDIR /build
ARG SNMP_PROFILE
RUN make -j ${SNMP_PROFILE} QOBF=qobf && cp /build/build_${SNMP_PROFILE}/agent /agent
