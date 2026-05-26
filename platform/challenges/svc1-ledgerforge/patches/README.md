# Patches

Each subdirectory ships patches that close one intended vulnerability in the
matching flagstore. Apply from the `svc1-ledgerforge/` root with

```
patch -p1 < patches/flagstore-0/vuln-a-canonicalization.patch
```

After applying every patch in a flagstore directory the service-level test
suite (`cargo test`) and the checker (sync wrapper at `checker/checker.py`
and the enochecker3 at `checker/src/checker.py`) must still pass against a
freshly built container. CI exercises this in the `sla-after-patch` job.

| Patch | Flagstore | Bug class |
|---|---|---|
| `flagstore-0/vuln-a-canonicalization.patch` | 0 (wire-transfer) | path-canonicalization mismatch on /api/read |
| `flagstore-0/vuln-b-snapshot-claim-prefix.patch` | 0 (wire-transfer) | substring-as-ACL on /api/snapshots/.../export |
| `flagstore-0/vuln-c-lfql-load-public-bypass.patch` | 0 (wire-transfer) | LFQL LOAD ignores doc.public |
| `flagstore-1/vuln-d-length-extension.patch` | 1 (settlement-note) | viewer token uses sha256(secret\|\|…) instead of HMAC |
| `flagstore-2/vuln-e-empty-scope-universal.patch` | 2 (treasury-key) | empty viewer scope set means universal access |
