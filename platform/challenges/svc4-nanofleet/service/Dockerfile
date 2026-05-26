FROM golang:1.23-bookworm AS builder

WORKDIR /build
COPY svc4-nanofleet/service/go.mod ./go.mod
COPY svc4-nanofleet/service/cmd ./cmd
COPY svc4-nanofleet/service/internal ./internal
RUN go build -o nanofleet ./cmd/nanofleet

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -u 10004 appuser
WORKDIR /app
COPY --from=builder /build/nanofleet /app/nanofleet
COPY svc4-nanofleet/service/static /app/static
COPY svc4-nanofleet/service/firmware /app/firmware
COPY svc4-nanofleet/service/fixtures /app/fixtures
RUN mkdir -p /var/lib/nanofleet \
    && chown -R appuser:appuser /app /var/lib/nanofleet
USER appuser

CMD ["/app/nanofleet"]
