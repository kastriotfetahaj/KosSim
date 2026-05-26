# NanoFleet — architecture

NanoFleet is a single-container Go (`net/http`) service that simulates a small
drone-telemetry orchestrator. It exposes one public TCP port (8080) and
persists state to a JSON file under `$NANOFLEET_DATA_DIR` (default
`/var/lib/nanofleet`).

## Process layout

```
+--------------------------------------------------------------+
|  nanofleet (Go, port 8080)                                   |
|                                                              |
|  routes ─────► routeCommand          ─────► state.Store      |
|         ├───► registerAgent / Schedule                       |
|         ├───► firmwareIssue / firmwareRead (manifest token)  |
|         ├───► diagnosticPayload (JWT-like job token)         |
|         ├───► tlvDecode / firmwareBlob (legacy)              |
|         └───► /service, /api/nodes, /health, /whoami         |
+--------------------------------------------------------------+
                          │
                          ▼
              /var/lib/nanofleet/state.json
```

There is no database. All state — flags per (tick, variant), drone nodes,
blob index, scheduled jobs — lives in a single in-memory map guarded by
`state.Store.Lock`, with each mutation snapshotted to disk via JSON. WAL is
unnecessary because state is rebuilt deterministically from disk on boot.

## Flagstore layout

Each flagstore stores its flag inside a synthetic node whose `Data` field
holds the round's plaintext flag. The `Kind` discriminator records which
flagstore minted the node so the SLA verifier can keep them apart.

| Flagstore | Variant | Node kind     | Surface                                     |
|-----------|---------|---------------|---------------------------------------------|
| 0         | 0       | `secret`      | `/api/route/<chain>?token=...`              |
| 1         | 1       | `manifest`    | `/api/v2/firmware/read?manifest=...&blob=...` |
| 2         | 2       | `diagnostic`  | `/api/v2/jobs/diagnostic?token=...`         |

The `attack_info` payload is consistent across flagstores: `{"a", "b", "p"}`
where `a` is the node id, `b` is the blob id, and `p` is the variant.

## Tokens

NanoFleet currently mints three independent token formats. All three use
`base64url` everywhere and HMAC-SHA-256 as the underlying primitive.

- **Route tokens** (`token.Sign`) — `body64.sig` with body `{"prefix": "..."}`.
  Issued by `/api/routes/diag-token` for the literal prefix `diag`.

- **Firmware manifest tokens** (`firmware.Issue`) — `body64.sig` with body
  `{"blob": "...", "ttl": ...}`. Issued by `/api/v2/firmware/issue?blob=...`
  but only for nodes whose kind is `public`.

- **Diagnostic job tokens** (`jobs.IssueHS256`) — JWT-like
  `header64.payload64.sig` with header `{"alg":"HS256"}` (intended) or
  `{"alg":"KID","kid":"..."}` (unintended). Payload is
  `{"node": "...", "scope": "..."}`.

## Persistence

`state.Store.persist()` writes the full state as JSON on every mutation.
A separate `jobs/latest.log` file records the current node count for
operator dashboards. Both files live under `$NANOFLEET_DATA_DIR` and are
chowned to the `appuser` (uid 10004) by the Dockerfile.
