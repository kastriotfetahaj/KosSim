FROM oven/bun:1.1

WORKDIR /app
COPY svc3-specterlog/service/package.json ./package.json
COPY svc3-specterlog/service/tsconfig.json ./tsconfig.json
RUN bun install --production
COPY svc3-specterlog/service/src ./src
COPY svc3-specterlog/service/static ./static

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && adduser --disabled-password --gecos "" appuser \
    && mkdir -p /var/lib/specterlog/blobs /var/lib/specterlog/streams \
    && chown -R appuser:appuser /app /var/lib/specterlog

USER appuser

ENV SPECTERLOG_DATA_DIR=/var/lib/specterlog \
    SPECTERLOG_STATIC_DIR=/app/static \
    PORT=8080

EXPOSE 8080

CMD ["bun", "src/main.ts"]
