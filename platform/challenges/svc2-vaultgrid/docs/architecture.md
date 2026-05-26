# VaultGrid architecture

VaultGrid ships as three cooperating processes per team. Only the storage
daemon listens on the public ingress port; the two sidecars sit on an
internal docker network and are reached through the storage daemon's proxy
routes.

```
        +------------------------+
client →| vaultgrid (C++, 8080) |←→ public HTTP, accounts, objects, repair
        +------------------------+
                 │ internal RPC over docker bridge
        ┌────────┴────────┐
        ▼                 ▼
+----------------+  +---------------+
| vaultgrid-crypt|  | vaultgrid-feed|
| (Rust, 4102)   |  | (Go, 4103)    |
+----------------+  +---------------+
        │                 │
        ▼                 ▼
   crypt.db          feed.db + stream.log
   (SQLite WAL)      (SQLite + append-only log)
```

## Process responsibilities

| Container | Language | Stores |
|---|---|---|
| `vaultgrid` | C++20 + sqlite3 | objects, leases, shards (flagstore 0), accounts, sessions, audit |
| `vaultgrid-crypt` | Rust + axum + rusqlite | manifests as AES-128-CBC + PKCS#7 ciphertext (flagstore 1) |
| `vaultgrid-feed` | Go + net/http + sqlite | append-only TLV record log (flagstore 2) |

## Data layout

- `/var/lib/vaultgrid/state.db` — primary SQLite WAL on the storage daemon.
- `/var/lib/vaultgrid-crypt/crypt.db` — encrypted manifest store.
- `/var/lib/vaultgrid-feed/feed.db` plus `stream.log` — index and raw stream.

Each container's data dir is a named docker volume in the generated
`docker-compose.generated.yml`, scoped per team
(`vaultgrid_<team>_data`, `vaultgrid_crypt_<team>_data`,
`vaultgrid_feed_<team>_data`).

## Inter-process trust

The two sidecars trust requests bearing the shared `X-Checker-Secret`
header for write paths. The storage daemon forwards public-facing
requests to the sidecars under the `/api/crypt/*` and `/api/feed/*`
prefixes without injecting that header, so attacker-controlled requests
cannot impersonate the storage daemon.
