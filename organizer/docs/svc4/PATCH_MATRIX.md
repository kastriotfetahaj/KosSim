# Patch Matrix - svc4 nanofleet

Organizer-only.

| Field | FS0 |
|---|---|
| Vulnerability name | Route compound command shadowing |
| Affected flagstore | 0 |
| Attack surface | `/api/route/:command` |
| Root cause | Authorization checks only that the whole route starts with the token prefix, then executes semicolon-separated subcommands. |
| Exploit idea | Use a diagnostic token for `diag` and append `;read:<node>` to read protected telemetry. |
| Exploit steps | Fetch diag token; call `/api/route/diag;read:<a>`; print telemetry data. |
| Realism | Fleet routers commonly authorize route prefixes before dispatch expansion. |
| Difficulty | Medium |
| Discoverability | Medium |
| Patchability | High |
| Impact | Device telemetry disclosure. |
| Expected solve path | Parse first, authorize each command, then execute. |
| Rabbit holes near it | JWT inspector, CRC collision route, debug pprof stub. |
| Why rabbit holes are safe | They report fixed diagnostics and do not touch node data. |
| Reference patch | `organizer/patches/svc4/vuln0.patch` rejects compound routes for prefix tokens. |
| Regression tests | Route exploit works before patch and route is denied after patch. |
| Checker coverage | Checker exercises node listing, diag route, TLV decode, and ops routes. |
| attack_info fields | `a` node id, `b` blob id, `p` flagstore. |
| Persistence notes | Nodes and jobs are stored under `/var/lib/nanofleet`. |

| Field | FS1 |
|---|---|
| Vulnerability name | TLV length capability confusion |
| Affected flagstore | 1 |
| Attack surface | `/api/tlv/decode` |
| Root cause | A diagnostic length value returns raw node data without checking node class. |
| Exploit idea | Call TLV decode with `length=260` for a secret node from attack_info. |
| Exploit steps | Request `/api/tlv/decode?node=<a>&length=260`; hex-decode `value_hex`. |
| Realism | Device tooling often grants broad access to diagnostic binary decoders. |
| Difficulty | Low-medium |
| Discoverability | Medium |
| Patchability | High |
| Impact | Single device flag disclosure. |
| Expected solve path | Gate raw decode by capability or node public class. |
| Rabbit holes near it | Firmware manifest and random seed diagnostics. |
| Why rabbit holes are safe | They do not authorize private node data when patched. |
| Reference patch | `organizer/patches/svc4/vuln1.patch` allows raw decode only for public nodes. |
| Regression tests | TLV exploit succeeds before patch and returns only kind after patch. |
| Checker coverage | Checker validates benign TLV decode still works. |
| attack_info fields | `a` node id, `b` blob id. |
| Persistence notes | Node map is durable JSON. |
