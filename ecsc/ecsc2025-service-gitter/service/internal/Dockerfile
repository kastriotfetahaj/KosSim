FROM oven/bun:1.2.23-slim@sha256:9654aa08d4b7e778b84148921bab8edc1409c8d0a85707b8c801dd7cf1878971
ENV DEBIAN_FRONTEND=noninteractive
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    --mount=type=bind,source=./repro-sources-list.sh,target=/usr/local/bin/repro-sources-list.sh \
    repro-sources-list.sh && \
    apt-get update && \
    apt-get install -y git npm && \
    : "Clean up for improving reproducibility (optional)" && \
    rm -rf /var/log/* /var/cache/ldconfig/aux-cache

COPY src/ /opt/
WORKDIR /opt/

RUN npm ci

CMD env $(cat /init-config/.env) bun run server.js
