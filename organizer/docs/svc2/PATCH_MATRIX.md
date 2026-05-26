# Patch Matrix - svc2 vaultgrid

Organizer-only.

| Field | FS0 |
|---|---|
| Vulnerability name | Repair grant context confusion |
| Affected flagstore | 0 |
| Attack surface | HTTP repair endpoint and TCP repair protocol |
| Root cause | Repair ticket validation checks the object prefix but not the exact shard scope. |
| Exploit idea | Use one lease ticket to retrieve all shards for the object and reconstruct the protected payload. |
| Exploit steps | Read attack_info `a` and `b`; request lease ticket; fetch s0, s1, s2; XOR shards. |
| Realism | Repair workflows often split session authorization from operation authorization. |
| Difficulty | Medium |
| Discoverability | Medium |
| Patchability | High |
| Impact | Full object recovery. |
| Expected solve path | Bind ticket to object and shard, and issue per-shard grants. |
| Rabbit holes near it | CRC, grant expiry, protobuf descriptor, AES audit. |
| Why rabbit holes are safe | They expose diagnostics and integrity metadata, not authorization bypasses. |
| Reference patch | `organizer/patches/svc2/vuln0.patch` requires exact object/shard ticket binding. |
| Regression tests | Repair exploit succeeds before patch and shard fanout fails after patch. |
| Checker coverage | Checker requests a ticket and a shard, then rebuilds normal preview. |
| attack_info fields | `a` object id, `b` lease id, `c` meta id, `p` flagstore. |
| Persistence notes | State and shards are written under `/var/lib/vaultgrid`. |

| Field | FS1 |
|---|---|
| Vulnerability name | Metadata recovery overflow |
| Affected flagstore | 1 |
| Attack surface | `/api/meta/:id?view=truncated&limit=...` |
| Root cause | Large truncated views return the raw object payload as an overflow diagnostic. |
| Exploit idea | Query the meta id from attack_info with an oversized limit and decode the hex overflow. |
| Exploit steps | Request meta view with `limit=65535`; hex-decode `overflow_hex`; print flag. |
| Realism | Preview paths frequently expose internal buffers meant for operators. |
| Difficulty | Low-medium |
| Discoverability | Medium |
| Patchability | High |
| Impact | Single object disclosure. |
| Expected solve path | Keep diagnostics bounded and never include data buffers. |
| Rabbit holes near it | Reed-Solomon mode flags and checksum collision route. |
| Why rabbit holes are safe | They are public diagnostics and do not read shard bytes. |
| Reference patch | `organizer/patches/svc2/vuln1.patch` returns a limit error instead of overflow bytes. |
| Regression tests | Meta exploit succeeds before patch and returns no `overflow_hex` after patch. |
| Checker coverage | Checker validates ordinary metadata remains available. |
| attack_info fields | `c` meta id. |
| Persistence notes | Meta index is regenerated from persisted state. |
