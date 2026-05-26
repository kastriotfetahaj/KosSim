# KosSim — ECSC-Grade Upgrade Design

**Audience:** organizers only. Do not mount into player containers.

This document is the spec for upgrading all five KosSim services to
ECSC-grade quality (~95–100 / 100). It is the source of truth for the
multi-turn implementation that follows.

## Conventions

- **Flagstore index** matches `variant_id` in checker tasks (0-based).
- **Noise variant index** is independent of flagstore index.
- **attack_info** is JSON, deterministic given the flag, used by attackers
  to locate the flag on the victim service.
- **Persistence** must survive container restart. Volumes mounted in
  `docker-compose.yml`.
- **Player-visible** = files inside the service container. **Organizer-only**
  = everything under `organizer/`.

Each service section ends with a checklist that maps directly to follow-up
turn deliverables.

---

# svc1 ledgerforge (Rust / Axum)

## Theme

A signed Merkle ledger with **branches** (think `git` without remote): each
tenant maintains a chain of commits, each commit holds a payload, and every
commit is provable via a Merkle proof from the branch tip.

## Player interaction (unique)

1. **Web GUI** at `/` (rendered from existing `static/`) — browse branches,
   inspect commits, request proofs.
2. **Signed-CLI HTTP API** at `/api/v1/*` — meant to be driven by a small
   `ledger` CLI binary shipped to teams. JSON in, JSON out, every mutating
   call carries an HMAC over `(tenant_id, branch, sequence, body)`.
3. **Webhook** at `/hooks/commit` — for noise.

Picking GUI + signed-CLI distinguishes svc1 from the others (all of which
avoid HTML GUIs).

## Persistence

- SQLite at `/var/lib/ledgerforge/ledger.db` (volume-mounted).
  - `branches(id, tenant_id, name, tip_hash, signed_at)`
  - `commits(hash, branch_id, prev_hash, payload_path, depth, signed_by)`
  - `proofs_cache(commit_hash, root_hash, proof_blob)`
- Payloads stored under `/var/lib/ledgerforge/payloads/<bb>/<commit_hash>` —
  the `<bb>` shard prefix is the first byte of the hash.
- WAL append-only log at `/var/lib/ledgerforge/wal.log` for replay debug.

## Vulnerabilities

### Flagstore 0 — Path-canonicalization across branch namespaces (KEEP, evolve)

- **Root cause.** Branch names are stored verbatim but the payload-path
  derivation uses `<bb>/<commit_hash>` where `<bb>` is computed from the
  *first byte of the branch's `name` field rather than the hash.* When a
  branch is created with a name beginning with hex chars matching another
  branch's hash prefix, a read of `branches/X/commits/H` resolves to the
  other branch's payload directory.
- **Disguise.** Code splits the path derivation across `state.rs`
  (`shard_for_branch`) and `ledger.rs` (`payload_path`). The variable
  reads as `shard` not `prefix`. Tests look like they verify isolation
  because they check by branch-id, not by name.
- **Why realistic.** This kind of sharding optimization is a real-world
  trick to avoid hot-spotting; the bug appears when name handling and
  hash handling drift apart.

### Flagstore 1 — Merkle-proof binding confusion (NEW)

- **Root cause.** The `verify_proof(root, leaf, proof)` function does not
  bind the *branch_id* into the leaf hash. Two branches whose tip hashes
  happen to match (which can be forced by replaying a commit) verify
  against each other's proofs. The HMAC on the proof request binds
  `(tenant_id, branch_name, leaf_hash)` but **not** `(branch_id)`.
- **Exploit shape.** Attacker creates a branch with a name colliding with
  victim's branch hash prefix, replays the victim's tip commit (publicly
  visible), then requests `GET /api/v1/proof?leaf=<victim_leaf>` — the
  cached proof from the victim's branch verifies against the attacker's
  branch, revealing the leaf payload (the flag).
- **Disguise.** The signing function is in `crypto.rs`,
  `proof_envelope_v2`, and looks fully bound — but the bound `branch_name`
  is the *attacker-controlled* request field. Subtle.

### Flagstore 2 — Snapshot replay via stale signed envelope (NEW, OPTIONAL)

- **Root cause.** Signed snapshot envelopes include
  `(branch_name, tip_hash, signed_at)` but no nonce/branch_id. After a
  branch is rewound (admin operation), an attacker can replay an older
  signed snapshot to *reintroduce* a payload that was rolled back, leaking
  the previously-current flag.
- **Note.** Optional. Implement if time permits; otherwise keep flagstore
  count at 2 for svc1.

## Rabbit holes

- Multiple hash formats (hex, base32, base58) in the wire format. All
  three canonicalize correctly — the bug is *not* a format-confusion.
- `/_debug/digest` endpoint exposes the current Merkle root. Looks like
  an info leak; it's already public.
- `compact_branch()` routine that rebuilds the proof cache. Looks
  racy/dangerous; protected by a per-branch tokio mutex correctly.
- `pending_admin.lf` migration file with a hashed admin password. The
  password hash is BLAKE2 — fine. Hashes nothing flag-related.
- `query.rs` has a "filter expression" mini-language that looks like
  injection bait; it's a closed grammar with no DB passthrough.

## Noise variants

- **noise 0**: post a benign commit on a fresh branch, then read its tip.
- **noise 1**: open a webhook subscription, push an event, verify delivery.

## attack_info schema

```json
{
  "branch": "trail-acid-37",
  "tenant_id": 71,
  "tip_hash": "9f3a…",
  "flagstore": 0 | 1
}
```

- For flagstore 0: includes `payload_shard` (the hex byte that collides).
- For flagstore 1: includes `proof_envelope_v2` (the public signed root).

## Checker workflow (PUTFLAG / GETFLAG / NOISE / HAVOC)

- **PUTFLAG fs0**: register a tenant, create a branch, post a commit
  whose payload contains the flag, store branch+tip in checker DB.
- **PUTFLAG fs1**: same as fs0 but additionally request and cache a
  signed proof envelope, store envelope in attack_info.
- **GETFLAG fs0**: re-fetch the commit via signed CLI; assert payload
  == flag.
- **GETFLAG fs1**: re-fetch via proof endpoint; assert.
- **PUTNOISE 0**: post commit with random payload (~512 B). Store ref.
- **GETNOISE 0**: read back, assert match.
- **PUTNOISE 1**: subscribe via webhook, push event, store delivery id.
- **GETNOISE 1**: query delivery log, assert event present.
- **HAVOC**: random walk of GUI endpoints (`/branches`, `/branches/X`,
  `/commits/H`, `/_debug/digest`), assert all 200s with valid JSON. One
  pass also exercises pagination edge cases (`limit=0`, `limit=1000`).
- **MUMBLE vs DOWN**: connection refused → DOWN. 5xx → DOWN. 4xx on
  known-good request → MUMBLE. JSON shape mismatch → MUMBLE.

## Deliverables for follow-up turn

- [ ] Rust: add SQLite + payload-FS persistence (sqlx).
- [ ] Rust: wire flagstore 1 (Merkle proof envelope endpoints).
- [ ] Rust: rabbit holes (compact_branch, pending_admin, query mini-lang).
- [ ] Checker: full ENOChecker3-style, ~600 LOC, both flagstores + noise
      + HAVOC + attack_info.
- [ ] `organizer/exploits/svc1/exploit_fs0.py` — path collision.
- [ ] `organizer/exploits/svc1/exploit_fs1.py` — proof rebinding.
- [ ] `organizer/patches/svc1/{vuln0.patch,vuln1.patch,all.patch}`.
- [ ] `organizer/docs/svc1/PATCH_MATRIX.md`.
- [ ] `tests/integration/test_svc1.py` — exploit-vs-unpatched + exploit-vs-patched.
- [ ] `docker-compose.yml` volume mounts for `/var/lib/ledgerforge`.

---

# svc2 vaultgrid (C++20)

## Theme

Erasure-coded blob vault with tenant-scoped objects, per-shard storage,
and an explicit "repair session" protocol for healing degraded shards.

## Player interaction (unique)

1. **Custom binary-ish TCP protocol** on port 4101 (line-framed JSON
   over TCP with HMAC trailers). This is the *only* mutating interface.
2. **CLI** `vault` ships to teams (single static C++ binary).
3. Read-only HTTP at `:8080/health` and `:8080/metrics` for ops.

## Persistence

- Per-shard files at `/var/lib/vaultgrid/shards/<tenant>/<object>/<idx>.shard`.
  Each shard has a 64-byte header (magic, tenant_id, object_id, shard_idx,
  shard_count, recovery_k, crc32, reserved).
- Tenant directory permissions: 0750, owned by `vault` user.
- Repair-session journal at `/var/lib/vaultgrid/journal/sess_<id>.log`.

## Vulnerabilities

### Flagstore 0 — Confused deputy via HMAC repair grant (KEEP, evolve)

- **Root cause.** Repair grants are signed with HMAC over
  `(object_id, shard_idx, expiry)` but **not** `(tenant_id)`. An attacker
  who owns object `O` in tenant A can craft a grant that, when presented
  to tenant B's repair queue, repairs B's shard with attacker-supplied
  data — or, in read-mode, returns B's shard contents.
- **Disguise.** Tenant binding lives in a separate `auth_session` struct
  passed alongside the grant; the binding is verified only on the
  *session* not on the *grant*. Code reads correct on first glance.

### Flagstore 1 — Shard-index off-by-one in Reed-Solomon recovery (NEW)

- **Root cause.** When `shard_count == recovery_k` (a degenerate but
  legal config for tiny objects), the recovery routine reads from
  `recovery_buffers[recovery_k]` after appending parity — which is a
  one-past-the-end read of the *parity* shard, returning data that
  reveals the original blob without holding any shard token.
- **Disguise.** The bug lives in `rs.cpp::recover_into()` inside a loop
  that looks like it correctly bounds `i < recovery_k`. The off-by-one
  is in a separate "tail completion" branch that's only reachable in
  the degenerate config — which the service silently uses for blobs
  smaller than 1KB (flags qualify).

### Flagstore 2 — Grant delegation scope union (NEW, OPTIONAL)

- **Root cause.** Grants can be delegated: `parent.delegate(child_scope)`.
  The implementation *unions* the scopes instead of *intersecting* them,
  so a holder of a narrow grant can produce a delegated grant with
  broader scope than they themselves hold.
- **Note.** Optional.

## Rabbit holes

- A `crc32` over shard headers that looks weak/trust-bearing — it's used
  only for offline corruption detection, not auth.
- `--recovery-k 0` CLI flag prints a "warning: degenerate" message but
  is a no-op.
- `mode=balanced` Reed-Solomon parameter is unused (dead config field).
- A `legacy_v1_grant` parser that looks like it might accept unsigned
  grants — it validates the same HMAC; the v1 difference is just envelope
  framing.
- A `repair_priority_queue` with a comparator that looks racy; protected
  by a `std::mutex` correctly.

## Noise variants

- **noise 0**: PUT a small blob, GET it back, assert.
- **noise 1**: PUT a blob, intentionally scrub one shard, request repair,
  verify recovery succeeds.

## attack_info schema

```json
{
  "tenant_id": 42,
  "object_id": "obj-9c1a3",
  "shard_count": 4,
  "recovery_k": 3,
  "flagstore": 0 | 1,
  "repair_session_hint": "if recovering, start with idx=2"
}
```

## Checker workflow

- Speaks the TCP protocol directly (no shell-out to the CLI; we vendor
  the protocol).
- PUTFLAG/GETFLAG fs0: store flag as object, attack_info includes object
  metadata.
- PUTFLAG/GETFLAG fs1: store flag in a small object (force degenerate
  config), attack_info nudges toward recovery flow.
- HAVOC: corrupt a shard, request repair, verify; also exercise the
  metrics endpoint.

## Deliverables for follow-up turn

- [ ] C++: SQLite metadata index + on-disk shard FS layout.
- [ ] C++: repair-session protocol cleanup.
- [ ] C++: rabbit holes (legacy_v1_grant, mode=balanced, etc.).
- [ ] Checker: TCP-speaking, ~700 LOC.
- [ ] Exploits for fs0, fs1.
- [ ] Patches for vuln0, vuln1, all.
- [ ] PATCH_MATRIX, integration tests, volume mounts.

---

# svc3 specterlog (TypeScript / Bun)

## Theme

A streaming event-log explorer: producers push events to named streams,
consumers subscribe via WebSocket with a signed cursor that advances as
events flow.

## Player interaction (unique)

1. **WebSocket protocol** at `ws://svc:8080/ws` — primary interface.
   Sub-protocol: `specterlog-v1`. Messages are length-prefixed CBOR.
2. **Minimal web UI** at `/` for browsing streams (read-only).
3. **REST control plane** at `/api/streams` for creating streams and
   minting cursors.

The WebSocket-first model differentiates svc3 from everything else.

## Persistence

- NDJSON append log per stream at `/var/lib/specterlog/streams/<id>.ndjson`.
- SQLite at `/var/lib/specterlog/meta.db`:
  - `streams(id, owner_tenant, name, created_at, compacted_offset)`
  - `cursors(id, stream_id, owner_tenant, position, sig, expires_at)`
  - `subscriptions(id, cursor_id, started_at)`

## Vulnerabilities

### Flagstore 0 — Cursor rebinding via stream override (KEEP, evolve)

- **Root cause.** The signed cursor envelope includes `(cursor_id,
  position, expires_at)` but **not** `(stream_id)`. The client sends
  `{cursor, stream_override}` in the SUBSCRIBE message; the server uses
  `stream_override` for the read but verifies the cursor signature with
  `cursor.stream_id` (the cursor's *own* field). A victim's cursor can
  be replayed against the attacker's stream subscription, leaking events.

### Flagstore 1 — Filter policy bypass via prefix collision (NEW)

- **Root cause.** Filters are stored as `^prefix.*` regex strings.
  Stream names allow `/` and `:` separators. A filter like
  `^auth/.*` is meant to gate access to `auth/admin`, but a stream
  named `auth/` followed by NUL terminator (which the JSON parser
  accepts via ` `) bypasses the filter because Bun's regex engine
  treats the NUL as a literal terminator at the JS string boundary.
- **Disguise.** The filter check looks correct; the bypass requires
  understanding the NUL handling in the producer-side stream name
  validator vs the consumer-side filter regex.

### Flagstore 2 — Compaction race window (NEW, OPTIONAL)

- **Root cause.** During background compaction, `compacted_offset` is
  bumped *before* the new file is renamed into place. A subscriber whose
  position falls in the gap reads from the old stream file *via the new
  offset*, leaking events from another tenant whose compaction was
  interleaved.

## Rabbit holes

- A `compression: brotli` option on streams. Looks like it might leak
  via length oracle; doesn't, lengths are padded to 64-byte multiples.
- "Tombstone" event type with a special `__tombstone__` payload. Looks
  like a UAF target; safely garbage-collected.
- Cursor encoding uses a custom base32 variant. Correct; not the bug.
- `/api/streams/_health` returns aggregate counts — looks like info leak
  but it's per-tenant filtered.

## Noise variants

- **noise 0**: create a stream, publish 10 events, subscribe with cursor,
  read them back.
- **noise 1**: subscribe with a "tail" cursor (position=-1), produce events
  live, verify delivery.

## attack_info schema

```json
{
  "stream_id": "auth/admin-29c1",
  "owner_tenant": 17,
  "cursor_id": "cur-3f81",
  "flagstore": 0 | 1
}
```

## Checker workflow

- WebSocket client implemented in the checker (use `websockets` Python
  lib with CBOR framing).
- PUTFLAG fs0: create stream, publish flag-bearing event, mint cursor,
  store cursor blob in attack_info.
- GETFLAG fs0: subscribe, scroll to cursor, assert.
- PUTFLAG fs1: create stream with filter-policy enabled, publish flag.
- HAVOC: load test — burst 200 small events, verify ordering preserved.

## Deliverables for follow-up turn

- [ ] TS: NDJSON + SQLite persistence (volume-mounted).
- [ ] TS: WebSocket sub-protocol v1 with CBOR framing.
- [ ] TS: filter policy + compaction routine.
- [ ] Checker: WebSocket-driven, ~600 LOC.
- [ ] Exploits, patches, matrix, tests.

---

# svc4 nanofleet (Go)

## Theme

A "fleet control" platform for swarms of nano-devices. Operators register
devices, push command templates to them, and schedule jobs across the
fleet.

## Player interaction (unique)

1. **Fleet control dashboard** at `/dashboard` (htmx-style server-rendered
   pages, no SPA).
2. **Agent CLI** `nanoctl` for operators (REST under `/api/v2`).
3. **Background worker** runs scheduled jobs; players observe results via
   the dashboard.

## Persistence

- PostgreSQL (already in compose) — new schemas:
  - `fleet_devices(id, tenant_id, label, capabilities, last_seen)`
  - `command_templates(id, tenant_id, name, body, vars_schema)`
  - `jobs(id, tenant_id, template_id, schedule, state, retry_count, result)`
- A `routes` table maps *external* HTTP paths to *internal* job IDs;
  this is where vuln 0 lives.

## Vulnerabilities

### Flagstore 0 — Route shadowing via radix-tree precedence (KEEP, evolve)

- **Root cause.** Route registry uses a radix tree. Dynamic operator
  routes are inserted with full priority; built-in admin routes use
  a `/admin/*` prefix that *should* take precedence but the tree's tie-
  breaker returns the longer pattern first. An operator route named
  `/admin/jobs/{id:re:.*}` (with a regex-typed param) shadows the
  built-in `/admin/jobs/:id`.
- **Disguise.** The "regex-typed param" feature looks like a generic
  flexibility add; the precedence rule is in a separate file
  (`routing/radix.go::compareSpecificity`) and is only buggy when the
  pattern includes a regex segment.

### Flagstore 1 — Capability confusion in template vars (NEW)

- **Root cause.** Command templates can reference variables: `${user.id}`,
  `${device.label}`, etc. The resolver walks a JSON document with
  *protected fields*: `${owner.token}` is meant to be blocked. The
  resolver's protection set is namespaced per-template, but inheritance
  through `template.extends` does not carry the protection set. A
  child template can therefore deref a parent's protected field.
- **Disguise.** Template inheritance is a real feature; the protection-
  set bug is subtle.

### Flagstore 2 — Retry-state machine drift (NEW, OPTIONAL)

- **Root cause.** Job retries snapshot the job context to retry from
  the original state. The snapshot is keyed by `job_id` only; if a job
  is rescheduled across a tenant rename, the snapshot reads the wrong
  tenant.

## Rabbit holes

- DNS-style route aliases: `device-a.fleet.local`. Locked to the fleet
  domain via a hardcoded suffix check; looks like SSRF, isn't.
- Device-label normalizer using Unicode NFKC + IDNA. Looks dangerous
  (`İ` → `i`), but is correctly enforced both on input and on lookup.
- Retry exponential backoff with jitter. Pure math, no leakage.
- A `legacy_v1_route` registration endpoint that looks like an open
  registration but requires a valid operator token.

## Noise variants

- **noise 0**: register a device, list it, verify presence.
- **noise 1**: schedule a benign command, wait for completion, fetch result.

## attack_info schema

```json
{
  "tenant_id": 8,
  "device_label": "drone-7c3a",
  "template_name": "noop",
  "flagstore": 0 | 1,
  "route_hint": "/admin/jobs/<id>"
}
```

## Checker workflow

- Drives dashboard and `nanoctl` API. Verifies that scheduled jobs
  reach a terminal state.
- HAVOC: spawn 10 short-lived devices, schedule a noop on each,
  assert all reach SUCCESS.

## Deliverables for follow-up turn

- [ ] Go: PostgreSQL schemas + repositories.
- [ ] Go: radix-tree route registry.
- [ ] Go: template inheritance + protection sets.
- [ ] Go: rabbit holes.
- [ ] Checker: ~650 LOC.
- [ ] Exploits, patches, matrix, tests.

---

# svc5 policyforge (Elixir)

## Theme

ABAC policy engine: tenants define policies, the engine evaluates
`(subject, action, resource, env)` and returns ALLOW/DENY with a
trace. Includes a policy workbench (web GUI) and a JSON-RPC API for
programmatic evaluation.

## Player interaction (unique)

1. **JSON-RPC 2.0** at `/rpc` — `policy.create`, `policy.eval`,
   `policy.simulate`, `policy.version.pin`.
2. **Policy workbench GUI** at `/workbench` (LiveView).
3. **gRPC-like compact eval** at `/eval-compact` over CBOR for
   high-throughput callers.

## Persistence

- PostgreSQL:
  - `policies(id, tenant_id, name, version, body, parent_id, created_at)`
  - `evaluations(id, tenant_id, subject, action, resource, decision,
     trace, evaluated_at)`
  - `pins(tenant_id, policy_name, pinned_version)`

## Vulnerabilities

### Flagstore 0 — Eval cache context omission (KEEP, evolve)

- **Root cause.** The eval cache key is `hash(policy_id, subject_hash,
  action, resource_hash)`. Crucially, `subject_hash` excludes
  `subject.tenant_id`. Two tenants whose subjects share `(user_id,
  role)` will collide; the cached decision from tenant A is served
  to tenant B.

### Flagstore 1 — Policy versioning rollback race (NEW)

- **Root cause.** `policy.version.pin` accepts `version=latest` and
  resolves at apply-time, but the resolution and the pin write are not
  in the same transaction. An attacker can submit a fork of the victim's
  policy at the same `name` and time the pin to capture the fork as
  "latest", causing subsequent victim evaluations to route through the
  attacker-controlled policy and emit a trace that contains the secret.

### Flagstore 2 — Macro expansion shadowing (NEW, OPTIONAL)

- **Root cause.** Policies support macros: `@user.attrs.role`. A
  tenant-controlled attribute named `__macro__` is, due to a missing
  reserved-name check, treated as a macro definition during expansion
  and can shadow built-in macros like `@now()`.

## Rabbit holes

- Trace mode emits decision logs that look like they might leak; the
  trace is sanitized through a recursive struct walker that strips
  `_secret_` keys correctly.
- A "deny-by-default" rule that looks vacuous; it actually catches
  policy-not-found cases. Don't remove it.
- Decimal precision arithmetic in `<=`/`>=` matchers. Uses `Decimal`
  lib correctly.
- A `policy.dryrun` endpoint that looks like it might bypass the cache;
  it doesn't — uses a separate non-cached path.

## Noise variants

- **noise 0**: create a small policy, evaluate one decision against it,
  read trace back.
- **noise 1**: create policy v1, update to v2, pin v2, evaluate.

## attack_info schema

```json
{
  "tenant_id": 5,
  "policy_name": "approve-payment",
  "subject_pattern": "{\"user_id\":\"u-X\",\"role\":\"manager\"}",
  "flagstore": 0 | 1
}
```

## Checker workflow

- Speaks JSON-RPC + LiveView for HAVOC.
- HAVOC: stress eval cache (1000 evals/sec for 2s), assert no errors.

## Deliverables for follow-up turn

- [ ] Elixir: Ecto + PostgreSQL.
- [ ] Elixir: cache implementation + version pin endpoint.
- [ ] Elixir: macro expansion + rabbit holes.
- [ ] Checker: JSON-RPC + LiveView, ~600 LOC.
- [ ] Exploits, patches, matrix, tests.

---

# Player-visible vs organizer-only

| Path                                | Audience           |
|-------------------------------------|--------------------|
| `platform/challenges/svcN/service/` | players (mounted)  |
| `platform/challenges/svcN/checker/` | organizers (rotator runs it; not visible to teams) |
| `platform/challenges/svcN/exploits/` | organizers — should be moved to `organizer/exploits/svcN/` |
| `platform/challenges/svcN/patches/`  | organizers — should be moved to `organizer/patches/svcN/` |
| `platform/challenges/svcN/meta/`     | shared — only `service.json` ships |
| `organizer/`                        | organizers only — never mounted |
| `tests/`                            | CI only           |

# Global deliverables

- [x] Phase 2 design (this file)
- [x] Organizer/ scaffolding
- [x] Root Makefile with build/test/dev/checkers/exploits/patches/reset/lint/ci
- [x] docker-compose.override.yml for hot reload
- [x] .env.example covering all secrets
- [x] CI workflow stub (.github/workflows/ci.yml)
- [ ] svc1 end-to-end (next turn)
- [ ] svc2 end-to-end
- [ ] svc3 end-to-end
- [ ] svc4 end-to-end
- [ ] svc5 end-to-end
- [ ] Final cross-cutting validation pass

# Expected scoring after full upgrade

| Axis                          | After |
|-------------------------------|------:|
| Vuln quality & variety (/20)  | 19    |
| Stack diversity (/10)         | 10    |
| Checker quality (/20)         | 19    |
| Patches & docs (/15)          | 14    |
| Dev/build/test (/15)          | 14    |
| Production-readiness (/10)    | 10    |
| Realism / theme (/10)         | 10    |
| **Total**                     | **96**|

Realistic ceiling without dedicated months: ~96. Closing the last 4
points requires production deployment hardening (rate limiting, audit
trails, secret rotation) that is largely operational, not service-level.
