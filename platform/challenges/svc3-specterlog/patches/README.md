# Patches

Each subdirectory holds patches that fix one intended vulnerability in the
matching flagstore. Apply from the `svc3-specterlog/` root with

```
patch -p1 < patches/flagstore-0/vuln-a-cursor-stream-override.patch
```

After applying every patch in a flagstore directory, both the
service-level test suite (`bun test`) and the checker (sync wrapper at
`checker/checker.py` and the enochecker3 at `checker/src/checker.py`) must
still pass against a freshly built container. CI exercises this contract
in the `sla-after-patch` job.

| Patch | Flagstore | Bug class |
|---|---|---|
| `flagstore-0/vuln-a-cursor-stream-override.patch` | 0 (incident) | cursor protocol-state confusion |
| `flagstore-0/vuln-b-search-filter-substring.patch` | 0 (incident) | substring-as-ACL on /api/search |
| `flagstore-0/vuln-c-archive-window-startswith.patch` | 0 (incident) | substring-as-ACL on /api/archive plus archive-id disclosure on /api/events |
| `flagstore-1/vuln-d-download-actor-unsigned.patch` | 1 (evidence) | HMAC payload missing actor |
| `flagstore-2/vuln-e-view-token-alg-none.patch` | 2 (directive) | view-token verifier accepts alg=none |
