# KosSim Advanced Services

These services follow the ECSC service-package shape:

- `service/`: runnable vulnerable service with ENO-compatible checker endpoints.
- `checker/`: lightweight checker/smoke tooling for organizers.
- `exploits/`: reference exploit for the intended bug chain.
- `patches/`: hardening notes for players or organizers.
- `meta/`: service metadata used by tooling and documentation.

The platform-facing service names remain `svc1` through `svc5` for database,
scoreboard, and Docker Compose compatibility.

| Slot | Service | Runtime | Primary Themes |
| --- | --- | --- | --- |
| `svc1` | LedgerForge | Rust/Axum | Capability canonicalization, stale snapshots, query parser differential |
| `svc2` | VaultGrid | C++20 | Repair-token confusion, rebuild oracle, metadata truncation leakage |
| `svc3` | SpecterLog | TypeScript/Bun/Fastify | Cursor rebinding, projection leakage, archive replay confusion |
| `svc4` | NanoFleet | Go `net/http` | Route shadowing, TLV truncation, firmware manifest confusion |
| `svc5` | PolicyForge | Elixir Plug/Cowboy | Policy cache omission, DSL normalization bypass, snapshot tenant confusion |

Each service exposes two flagstores (`flagVariants = 2`), at least three
intended exploit paths, and at least five non-leaking rabbit-hole endpoints.
Public service UIs are interactive, but public `/attack-info` bug leaks are not
exposed by the services themselves; the game server still receives compact flag
IDs from `PUTFLAG`.
