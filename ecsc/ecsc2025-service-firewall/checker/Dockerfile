FROM debian:trixie-20250908-slim@sha256:c2880112cc5c61e1200c26f106e4123627b49726375eb5846313da9cca117337 AS builder

ADD --chmod=0755 --checksum=sha256:c125df9762b0c7233459087bb840c0e5dbfc4d9690ee227f1ed8994f4d51d2e0 \
    https://raw.githubusercontent.com/reproducible-containers/repro-sources-list.sh/v0.1.4/repro-sources-list.sh \
    /usr/local/bin/repro-sources-list.sh

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked --mount=type=cache,target=/var/lib/apt,sharing=locked \
    /usr/local/bin/repro-sources-list.sh && \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends --yes \
        gcc libc6-dev make && \
    rm -f /usr/local/bin/repro-sources-list.sh

COPY ./tools/ /tools/
RUN make -C /tools/

FROM debian:trixie-20250908-slim@sha256:c2880112cc5c61e1200c26f106e4123627b49726375eb5846313da9cca117337

ADD --chmod=0755 --checksum=sha256:c125df9762b0c7233459087bb840c0e5dbfc4d9690ee227f1ed8994f4d51d2e0 \
    https://raw.githubusercontent.com/reproducible-containers/repro-sources-list.sh/v0.1.4/repro-sources-list.sh \
    /usr/local/bin/repro-sources-list.sh

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked --mount=type=cache,target=/var/lib/apt,sharing=locked \
    /usr/local/bin/repro-sources-list.sh && \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends --yes \
        iproute2 git gosu libcap2-bin python3 python3-pip && \
    rm -f /usr/local/bin/repro-sources-list.sh

RUN pip install --break-system-packages --root-user-action=ignore "uv~=0.8.17"

RUN useradd --create-home --shell /bin/bash --uid 1000 checker

RUN --mount=type=bind,source=./src/pyproject.toml,target=/pyproject.toml \
    --mount=type=bind,source=./src/uv.lock,target=/uv.lock \
    --mount=type=bind,source=./with-pat.sh,target=/usr/local/bin/with-pat \
    --mount=type=secret,id=github-pat,env=GITHUB_PAT,required=true \
    --mount=type=tmpfs,target=/tmp/ \
    if [ -z "${GITHUB_PAT:-}" ]; then /bin/echo -e '\x1b[31mgithub-pat secret is not set (did you forget to set GITHUB_PAT?)\x1b[0m' >&2; exit 1; fi && \
    with-pat uv sync --exact --frozen

COPY --chown=checker:checker ./src/ /checker/
COPY --chmod=0500 entrypoint.sh /entrypoint.sh

# :(. But capabilities refuse to work.
COPY --from=builder --chmod=4555 /tools/fwmark /bin/fwmark
COPY --from=builder --chmod=4555 /tools/ip-wrapper /bin/ip-wrapper
COPY --from=builder --chmod=4555 /tools/tunctl /bin/tunctl

WORKDIR /
ENTRYPOINT ["/entrypoint.sh"]
