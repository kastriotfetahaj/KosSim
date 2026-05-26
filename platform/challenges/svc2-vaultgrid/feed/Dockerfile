FROM golang:1.22-bookworm AS builder
WORKDIR /build
COPY svc2-vaultgrid/feed/go.mod ./go.mod
COPY svc2-vaultgrid/feed/*.go ./
ENV CGO_ENABLED=1 GOFLAGS=-mod=mod
RUN go mod tidy && go build -o vaultgrid-feed .

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl libsqlite3-0 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -u 10003 feeduser \
    && mkdir -p /var/lib/vaultgrid-feed \
    && chown -R feeduser:feeduser /var/lib/vaultgrid-feed
WORKDIR /app
COPY --from=builder /build/vaultgrid-feed /app/vaultgrid-feed
USER feeduser
ENV VAULTGRID_FEED_DATA_DIR=/var/lib/vaultgrid-feed \
    VAULTGRID_FEED_ADDR=:4103
EXPOSE 4103
CMD ["/app/vaultgrid-feed"]
