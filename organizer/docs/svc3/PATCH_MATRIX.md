# Patch Matrix - svc3 specterlog

Organizer-only.

| Field | FS0 |
|---|---|
| Vulnerability name | Cursor stream rebinding |
| Affected flagstore | 0 |
| Attack surface | `/api/replay` and `/ws` subscription flow |
| Root cause | Signed cursor verification accepts the cursor while a request parameter can select a different stream. |
| Exploit idea | Mint a public cursor, replay it in delta mode against the private stream, and collect flag events. |
| Exploit steps | Fetch public cursor; call replay with `mode=delta&stream=private`; print private event bodies. |
| Realism | Cursor envelopes often bind position and expiry but omit every selector used by readers. |
| Difficulty | Medium |
| Discoverability | Medium |
| Patchability | High |
| Impact | Private stream disclosure. |
| Expected solve path | Bind stream id into the signed cursor or reject stream overrides. |
| Rabbit holes near it | Base64 cursor format, wasm map, rate-limit status. |
| Why rabbit holes are safe | They do not alter stream selection or cursor verification. |
| Reference patch | `organizer/patches/svc3/vuln0.patch` denies mismatched stream overrides. |
| Regression tests | Replay exploit works before patch and receives 403 after patch. |
| Checker coverage | Checker validates cursor minting, replay, archive, search, WebSocket health. |
| attack_info fields | `a` event id, `b` archive id, `p` flagstore. |
| Persistence notes | Events are persisted in state JSON and per-stream NDJSON. |

| Field | FS1 |
|---|---|
| Vulnerability name | Filter policy projection bypass |
| Affected flagstore | 1 |
| Attack surface | `/api/search` |
| Root cause | A user-controlled filter string can enable private rows by containing `public||private`. |
| Exploit idea | Request body projection with the mixed filter and collect flag bodies. |
| Exploit steps | Call `/api/search?project=body&filter=public||private`; print rows whose body is a flag. |
| Realism | Search projections and filter DSLs often drift from stream ACL checks. |
| Difficulty | Low-medium |
| Discoverability | Medium |
| Patchability | High |
| Impact | Private event disclosure. |
| Expected solve path | Treat filter strings as data and enforce ACL independently. |
| Rabbit holes near it | Tombstones and compression notes. |
| Why rabbit holes are safe | They affect storage format but not authorization. |
| Reference patch | `organizer/patches/svc3/vuln1.patch` disables private projection via public filters. |
| Regression tests | Search exploit prints flags before patch and no private rows after patch. |
| Checker coverage | Checker exercises public search and archive paths. |
| attack_info fields | `a` event id, `b` archive id. |
| Persistence notes | Search operates on persisted event records. |
