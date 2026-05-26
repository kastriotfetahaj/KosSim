# Patch Matrix - svc5 policyforge

Organizer-only.

| Field | FS0 |
|---|---|
| Vulnerability name | ABAC decision cache key omission |
| Affected flagstore | 0 |
| Attack surface | `/api/object/:id` and JSON-RPC policy evaluation |
| Root cause | Cache key includes user, tenant, and class, but omits object identity and owner. |
| Exploit idea | Warm the cache on a public incident object, then read a private incident object with the same class. |
| Exploit steps | Get guest session; read public id `b`; read private id `a`; print data. |
| Realism | Positive authorization caches often miss a context dimension. |
| Difficulty | Medium |
| Discoverability | Medium |
| Patchability | High |
| Impact | Private resource disclosure. |
| Expected solve path | Include object id, owner, subject, tenant, and policy version in cache key. |
| Rabbit holes near it | GraphQL ops route, renderer route, cookie flags report. |
| Why rabbit holes are safe | They expose only static diagnostics. |
| Reference patch | `organizer/patches/svc5/vuln0.patch` expands the cache key with object id and owner. |
| Regression tests | Cache exploit works before patch and receives denied after patch. |
| Checker coverage | Checker reads a public object and runs policy eval. |
| attack_info fields | `a` private object id, `b` public warmup id, `c` snapshot id, `p` flagstore. |
| Persistence notes | State is serialized under `/var/lib/policyforge/state.term`. |

| Field | FS1 |
|---|---|
| Vulnerability name | Snapshot tenant claim confusion |
| Affected flagstore | 1 |
| Attack surface | `/api/snapshot/:snap/object/:id` |
| Root cause | Snapshot read accepts `tenant=public` as a bypass for any object in the snapshot. |
| Exploit idea | Use attack_info snapshot and object id with `tenant=public`. |
| Exploit steps | Request snapshot object endpoint with `tenant=public`; print object data. |
| Realism | Simulation and snapshot APIs often use looser tenant claims than live policy evaluation. |
| Difficulty | Medium |
| Discoverability | Medium |
| Patchability | High |
| Impact | Historical policy object disclosure. |
| Expected solve path | Require tenant claim to match object tenant unless object is public. |
| Rabbit holes near it | Macro expansion and dry-run evaluation. |
| Why rabbit holes are safe | They do not override snapshot tenant checks. |
| Reference patch | `organizer/patches/svc5/vuln1.patch` compares claim to object tenant. |
| Regression tests | Snapshot exploit works before patch and is denied after patch. |
| Checker coverage | GETFLAG validates snapshot-backed object persists. |
| attack_info fields | `a` object id, `c` snapshot id. |
| Persistence notes | Snapshot map is stored with policy state. |
