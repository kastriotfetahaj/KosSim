FROM debian:trixie-20250908-slim@sha256:c2880112cc5c61e1200c26f106e4123627b49726375eb5846313da9cca117337

ADD --chmod=0755 --checksum=sha256:c125df9762b0c7233459087bb840c0e5dbfc4d9690ee227f1ed8994f4d51d2e0 \
    https://raw.githubusercontent.com/reproducible-containers/repro-sources-list.sh/v0.1.4/repro-sources-list.sh \
    /usr/local/bin/repro-sources-list.sh

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked --mount=type=cache,target=/var/lib/apt,sharing=locked \
    /usr/local/bin/repro-sources-list.sh && \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends --yes \
        openssl python3 && \
    rm -f /usr/local/bin/repro-sources-list.sh

COPY --chown=root:root --chmod=0500 init.py /init.py

CMD ["/usr/bin/python3", "/init.py", "/state"]
