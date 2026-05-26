# VaultGrid

VaultGrid is an erasure-coded object vault. The storage daemon (C++)
fans out to a crypt sidecar (Rust) for encrypted manifests and a feed
sidecar (Go) for append-only telemetry. Three flagstores, three
independent exploit paths, three languages.

## Layout

```
service/      C++20 storage daemon (the public HTTP face)
  src/        custom HTTP server, routes, accounts, audit, proxy, crypto util
  static/     SPA
crypt/        Rust + axum sidecar (flagstore 1 — CBC padding oracle)
feed/         Go + net/http sidecar (flagstore 2 — TLV range disclosure)
checker/
  checker.py  sync entry point used by the KosSim platform driver
  src/        enochecker3 async app (gunicorn + uvicorn)
exploits/     one independent exploit per flagstore
patches/      patches that close each intended vulnerability
docs/         architecture, threat model, runbook
meta/         service metadata
```

## Running

See `docs/runbook.md` for the single-machine bring-up.

```sh
SECRET=$(openssl rand -hex 16)
# Three docker build commands, three docker run commands - see runbook.
SERVICE_PUSH_SECRET=$SECRET python3 checker/checker.py http://127.0.0.1:8080
```

## Tests

```sh
make -C service                 # C++ build + lint
cargo build --release           # in crypt/
go build .                      # in feed/
```

CI runs cargo + go + make, then docker-builds all three images, then
sync-runs the checker plus all three exploits against the unpatched
stack, then walks the per-patch matrix verifying SLA holds and the
matching exploit fails.

## Threat model

See `docs/threat-model.md`.

## Intended vulnerabilities

<details>
<summary>SPOILERS - open only if you are not playing</summary>

| # | Flagstore | Bug | Where it lives | Patch |
|---|-----------|-----|----------------|-------|
| A | 0 - wire-transfer (XOR shards) | repair ticket prefix-only check accepts the same ticket for s0/s1/s2 | `service/src/routes.cpp` repair handler | `patches/flagstore-0/vuln-a-repair-ticket-shard.patch` |
| B | 0 - wire-transfer | `/api/rebuild` returns the reconstructed body as preview_hex | `service/src/routes.cpp` rebuild handler | `patches/flagstore-0/vuln-b-rebuild-preview.patch` |
| C | 0 - wire-transfer | `/api/meta/:id?view=truncated&limit=>4096` returns body as overflow_hex | `service/src/routes.cpp` meta handler | `patches/flagstore-0/vuln-c-meta-overflow.patch` |
| D | 1 - manifest (AES-CBC ciphertext) | distinguishable 400/422 responses on `/api/crypt/decrypt` form a CBC padding oracle | `crypt/src/main.rs` decrypt handler | `patches/flagstore-1/vuln-d-cbc-padding-oracle.patch` |
| E | 2 - feed record (TLV stream) | `/api/feed/range` returns raw bytes of the append-only log without auth | `feed/main.go` handleRange | `patches/flagstore-2/vuln-e-feed-range-auth.patch` |

Each exploit script in `exploits/` targets one bug:

- `exp1.py` exercises VULN A: pulls one ticket from the lease endpoint and
  reuses it for all three shards, then XORs to recover the flag.
- `exp2.py` exercises VULN D: classic CBC padding oracle against
  `/api/crypt/decrypt`, byte-by-byte plaintext recovery.
- `exp3.py` exercises VULN E: requests `/api/feed/range?offset=&length=`
  on the range endpoint, parses the TLV stream, extracts the flag.

VULNs B and C remain in the code as redundant paths to flagstore 0; the
patches close each independently and CI verifies SLA holds with any
subset applied.

</details>
