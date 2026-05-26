# Patches

Each subdirectory holds patches that close one intended vulnerability in
the matching flagstore. Apply from the `svc2-vaultgrid/` root with
`patch -p1 < <path>`.

The svc2 service runs as three containers (C++ storage daemon, Rust crypt
sidecar, Go feed sidecar). Patches A/B/C edit the C++ source, patch D
edits the Rust source, patch E edits the Go source.

| Patch | Flagstore | Bug class |
|---|---|---|
| `flagstore-0/vuln-a-repair-ticket-shard.patch` | 0 (wire-transfer) | confused-deputy: repair ticket prefix-only check |
| `flagstore-0/vuln-b-rebuild-preview.patch` | 0 (wire-transfer) | rebuild preview returns reconstructed bytes |
| `flagstore-0/vuln-c-meta-overflow.patch` | 0 (wire-transfer) | meta endpoint leaks body as overflow_hex |
| `flagstore-1/vuln-d-cbc-padding-oracle.patch` | 1 (manifest) | distinguishable CBC padding/JSON error codes |
| `flagstore-2/vuln-e-feed-range-auth.patch` | 2 (feed record) | /api/feed/range publicly dumps log bytes |
