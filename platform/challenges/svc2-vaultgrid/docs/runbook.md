# VaultGrid runbook

## Local single-machine bring-up

```sh
# Build all three images (run from platform/challenges/)
docker build -t vaultgrid-service -f svc2-vaultgrid/service/Dockerfile .
docker build -t vaultgrid-crypt   -f svc2-vaultgrid/crypt/Dockerfile .
docker build -t vaultgrid-feed    -f svc2-vaultgrid/feed/Dockerfile .

# Network + run
docker network create vg-net
SECRET=$(openssl rand -hex 16)
docker run -d --name vg-crypt --network vg-net --network-alias vaultgrid-crypt \
  -e SERVICE_PUSH_SECRET=$SECRET vaultgrid-crypt
docker run -d --name vg-feed --network vg-net --network-alias vaultgrid-feed \
  -e SERVICE_PUSH_SECRET=$SECRET vaultgrid-feed
docker run -d --name vg --network vg-net \
  -e SERVICE_PUSH_SECRET=$SECRET -e TEAM_NAME=local -e SERVICE_NAME=svc2 \
  -p 8080:8080 vaultgrid-service
```

## Common operator actions

- Health: `curl http://127.0.0.1:8080/health`
- Force a SQLite checkpoint on the storage daemon:
  `docker exec vg /bin/sh -c "sqlite3 /var/lib/vaultgrid/state.db 'PRAGMA wal_checkpoint(TRUNCATE);'"`
- Inspect audit log: `curl -H "X-Checker-Secret: $SECRET" -H 'Content-Type: application/json' ...`
  (the `/api/audit/recent` endpoint requires an admin session, see accounts module)

## Running the sync checker

```sh
SERVICE_PUSH_SECRET=$SECRET python3 checker/checker.py http://127.0.0.1:8080
```

Exits 0 on success and prints `{"status":"OK",...}`. Non-zero exit returns
`{"status": "DOWN" | "MUMBLE", "message": "..."}`.

## Running the async (enochecker3) checker

```sh
docker build -t vaultgrid-checker -f svc2-vaultgrid/checker/Dockerfile \
  svc2-vaultgrid/checker
docker run --rm -p 8500:8500 \
  -e SERVICE_PUSH_SECRET=$SECRET vaultgrid-checker
```

Then POST tasks at `http://127.0.0.1:8500` per the enochecker3 API.

## Patching workflow

```sh
patch -p1 < patches/flagstore-0/vuln-a-repair-ticket-shard.patch
docker build -t vaultgrid-service -f service/Dockerfile ../
# re-run checker to confirm SLA still passes
```

`patches/README.md` lists every patch and the bug it closes. CI re-runs
the sync checker against each patched build.
