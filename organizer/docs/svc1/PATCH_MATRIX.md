# Patch Matrix - svc1 ledgerforge

Organizer-only.

| Field | FS0 |
|---|---|
| Vulnerability name | Capability path canonicalization drift |
| Affected flagstore | 0 |
| Attack surface | `/api/grants/:label` and `/api/read` |
| Root cause | Scope is checked before path decoding and normalization, so a granted public prefix can be followed by encoded parent traversal. |
| Exploit idea | Obtain a public grant, request `/public/%2e%2e/vault/<id>`, and read the private ledger payload. |
| Exploit steps | Use attack_info `a` for the document id; fetch guest grant; request the normalized bypass path; print body. |
| Realism | Mirrors capability systems that validate a raw URL path separately from the storage resolver. |
| Difficulty | Medium-high |
| Discoverability | Medium |
| Patchability | High |
| Impact | Flag disclosure for one ledger object. |
| Expected solve path | Compare authorization path and resolved path in the read handler. |
| Rabbit holes near it | Hash formats, migration preview, timing probe, HMAC audit. |
| Why rabbit holes are safe | They do not dereference protected payloads and expose only public metadata. |
| Reference patch | `organizer/patches/svc1/vuln0.patch` canonicalizes before scope comparison. |
| Regression tests | Checker public read, exploit fs0 before patch, denied fs0 after patch. |
| Checker coverage | PUTFLAG stores a document; GETFLAG validates it; HAVOC checks Merkle/debug/query paths. |
| attack_info fields | `a` document id, `b` snapshot id, `c` class, `d` grant label, `t` tick, `p` flagstore. |
| Persistence notes | State is mirrored to `/var/lib/ledgerforge/state.json` and WAL text. |

| Field | FS1 |
|---|---|
| Vulnerability name | Snapshot proof binding omission |
| Affected flagstore | 1 |
| Attack surface | `/api/snapshots/:snap/export` |
| Root cause | The export claim treats `public:<doc>` as sufficient and does not require the target document itself to be public. |
| Exploit idea | Use attack_info snapshot and document id to export a private snapshot row under a public claim. |
| Exploit steps | Request `/api/snapshots/<b>/export?claim=public:<a>` and print the row body. |
| Realism | Snapshot export and proof APIs often drift from object-level authorization. |
| Difficulty | Medium |
| Discoverability | Medium |
| Patchability | High |
| Impact | Flag disclosure through historical ledger export. |
| Expected solve path | Bind export decisions to the document public bit or owner authorization. |
| Rabbit holes near it | Merkle root debug and LFQL query grammar. |
| Why rabbit holes are safe | Root values are public commitments and LFQL denies vault/private selectors. |
| Reference patch | `organizer/patches/svc1/vuln1.patch` filters snapshot rows to public documents. |
| Regression tests | Snapshot exploit succeeds before patch and receives no private rows after patch. |
| Checker coverage | PUTFLAG fs1 creates a snapshot; GETFLAG validates post-restart state. |
| attack_info fields | `a` document id, `b` snapshot id, `p` flagstore. |
| Persistence notes | Snapshot metadata persists with document records. |
