# Platform Services vs ECSC 2025 — Rating Report

**Reviewed:** 2026-05-26
**Re-rated:** 2026-05-26 (svc4 and svc5 brought to ECSC parity)
**Reference baseline:** `ecsc/ecsc2025-service-{Jitterish,firewall,gitter,heavensent}`
**Subjects:** `platform/challenges/svc{1..5}`

---

## TL;DR

| Service           | Vuln Design | Realism | Checker | Ops | **Overall** | Δ vs prior | Tier vs ECSC |
|-------------------|:-----------:|:-------:|:-------:|:---:|:-----------:|:----------:|:-------------|
| svc1-ledgerforge  | 8           | 8       | 8       | 9   | **8.3**     | —          | At baseline  |
| svc2-vaultgrid    | 9           | 9       | 7       | 9   | **8.5**     | —          | Above baseline (top of platform set) |
| svc3-specterlog   | 8           | 8       | 8       | 8   | **8.0**     | —          | At baseline  |
| svc4-nanofleet    | 8           | 7       | 8       | 9   | **8.0**     | +3.2       | At baseline (was 4.8) |
| svc5-policyforge  | 8           | 6       | 8       | 9   | **7.8**     | +3.0       | At baseline (was 4.8) |

**ECSC reference anchors** (same scale):

| Service     | Vuln | Realism | Checker | Ops |
|-------------|:----:|:-------:|:-------:|:---:|
| Jitterish   | 9    | 8       | 7       | 5   |
| Firewall    | 9    | 9       | 10      | 9   |
| Gitter      | 8    | 8       | 6       | 5   |
| Heavensent  | 10   | 8       | 7       | 6   |

**One-line verdict:** **All five platform services are now at or above ECSC baseline.** svc2 remains the strongest on premise; svc1 and svc4 lead on patch hygiene and CI maturity (and beat every ECSC service except Firewall on ops). The gap that existed for svc4 and svc5 — demo-grade execution around good vuln ideas — has been closed.

---

## Scoring rubric

Each dimension is scored 1–10 against the ECSC services as the anchor (≈ 7–9 range = ECSC-grade).

- **Vuln Design** — originality, depth, anti-AI quality, multi-step chaining, count, distribution across flagstores.
- **Realism / Code Quality** — production-likeness of the stack, code structure, language choice, dependency hygiene, internal threat model.
- **Checker** — coverage of getflag/putflag/havoc, SLA depth, noisestore/HAVOC variants, framework maturity, anti-cheat.
- **Ops Readiness** — Dockerfile, patches per vuln, CI workflow, runbook/architecture docs, exploit scripts shipped.

A service can be world-class on concept and still fail Ops — Jitterish itself only gets a 5 on Ops because it ships no patches and no build.sh, so the bar there is lower than you'd think.

---

## svc1-ledgerforge — **8.3 / 10** (at ECSC baseline)

**Stack:** Rust + axum, SQLite (WAL), single container, port 8080. ~2,666 LOC service.

### Vuln Design — 8/10
5 vulns across 3 flagstores. The headline bug is a SHA-256 **length-extension** on viewer tokens (`service/src/crypto.rs`, `settlements.rs`) — this is genuinely anti-AI: a static scanner or LLM grep won't flag it because the API surface looks fine; you have to reason about the hash construction. Flagstore-0 is intentionally over-supplied with three independent canonicalization/grant-confusion paths (VULN-A `/public/%2e%2e/vault/...`, VULN-B snapshot prefix, VULN-C LFQL `LOAD:public::`), giving defenders surface to patch progressively. Empty-scope-treated-as-universal (VULN-E) is a clean scope-confusion bug.

Versus ECSC: comparable to Gitter's path-traversal + struct-overlap mix (Gitter scored 8). Not as exotic as Jitterish's JIT-symbol override or Heavensent's LFSR feedback bug.

### Realism — 8/10
Idiomatic axum + tower stack, SQLite WAL with proper SIGTERM checkpoint, multi-stage Rust→debian-slim Dockerfile running as non-root. Threat model in README distinguishes untrusted/trusted roles. On par with Firewall's frontend or Gitter's Express service.

### Checker — 8/10
593-LOC async `checker/src/checker.py` on enochecker3, sync wrapper. `meta/service.json` declares 3 flagstores, 3 noisestores, **9 HAVOC variants** — that's the structured coverage ECSC checkers have and that Gitter (861 LOC, no separate exploit scripts) only partially achieves.

### Ops — 9/10
**5 patches with proper naming** (`patches/flagstore-0/vuln-a-canonicalization.patch`, etc.) — one per vuln. CI workflow (`.github/workflows/ci.yml`) lints, builds, runs checker, runs each exploit, applies each patch, and asserts SLA still holds. This is **better than Jitterish and Gitter**, which ship zero patches and no CI.

### Weaknesses
- No threat-model doc separate from README (svc2 does).
- No standalone architecture diagram.

---

## svc2-vaultgrid — **8.5 / 10** (top of platform set)

**Stack:** C++20 storage daemon (1,709 LOC) + Rust+axum `crypt` sidecar (316 LOC) + Go `feed` sidecar (345 LOC). 3 containers on internal docker bridge. Ports 8080 / 4102 / 4103.

### Vuln Design — 9/10
The crown jewel is VULN-D, a **classic AES-CBC padding oracle** in the Rust sidecar exposed via distinguishable 400/422 responses on `/api/crypt/decrypt`. This is real-world cryptanalysis (BEAST/Lucky-13 family) and your `exp2.py` (118 LOC) implements the byte-by-byte oracle properly — that's anti-AI in the strongest sense, because solving it requires implementing an iterative attack, not pattern-matching a CVE.

The flagstore-0 set (repair-ticket reuse, rebuild-preview leak, meta-overflow body return) plus VULN-E (`/api/feed/range` no-auth raw TLV bytes) gives you 5 vulns across 3 flagstores, including a polyglot inter-process trust model where sidecars trust `X-Checker-Secret` but not arbitrary public requests.

Versus ECSC: this is the only platform service whose vuln set sits next to **Heavensent (10) and Jitterish (9)** rather than behind them. The padding oracle in particular is more pedagogically valuable than Jitterish's JIT bugs because students can carry the technique elsewhere.

### Realism — 9/10
Genuinely polyglot architecture (C++ / Rust / Go) with realistic role separation: erasure-coded object store, key-management sidecar, append-only audit feed. This mirrors how real distributed storage systems are built, and it's closer to Firewall's 5-container realism than anything else in the platform set.

### Checker — 7/10
360-LOC sync checker. Tight, but **smaller than svc1/svc3 despite needing to coordinate three containers**. Given the architectural breadth, I'd expect more HAVOC depth here. Still ahead of Gitter's 861-LOC checker on coverage-per-LOC, but the absolute size is low.

### Ops — 9/10
Three separate Dockerfiles, internal docker network, explicit `docs/runbook.md` + `docs/architecture.md` + threat model. **5 patches**, CI, exploit-matrix validation. The docs are the best in the platform set.

### Weaknesses
- 3-container ops will hurt newer players debugging locally.
- Checker has the lowest LOC of svc1–svc3 — could use deeper SLA assertions on the inter-service paths.

---

## svc3-specterlog — **8.0 / 10** (at ECSC baseline)

**Stack:** TypeScript + Bun + Fastify, SQLite WAL, blob storage on disk. Single container, port 8080. ~2,289 LOC service.

### Vuln Design — 8/10
VULN-E is a textbook **JOSE `alg=none`** forgery on the view-token verifier (`service/src/tokens.ts`) — classic, but pedagogically valuable. VULN-A (signed-cursor stream override after verification in `/api/replay?mode=delta`) is the more interesting one: the cursor is signed but a query parameter is OR'd into the predicate *after* verification. That's the kind of subtle binding bug that's hard to spot in a code review and a static analyzer won't catch. VULN-D (signature omits `actor`, then `actor` read from querystring) is a clean signature-binding flaw.

Flagstore-0 again uses the multi-path pattern (VULN-A primary, B/C as exercises). 5 vulns / 3 flagstores.

### Realism — 8/10
SOC incident-replay scenario is novel and plausible. Bun + Fastify is a modern, real-world stack. Good module separation (routes / accounts / cases / briefs / attachments / admin / indexer). Less mature runtime than Rust/Go but defensible.

### Checker — 8/10
**738 LOC async checker** — the richest in the platform set. enochecker3, gunicorn+uvicorn, 9 HAVOC variants + noisestores. Comparable to ECSC checkers on structure.

### Ops — 8/10
5 patches with consistent naming, CI workflow with bun:test unit tests + exploit/patch matrix. WAL checkpoint on SIGTERM. Slightly behind svc2 only because it lacks an architecture/threat-model doc.

### Weaknesses
- Primary attack vector per flagstore is sometimes a single path (B/C as exercises) — fine for play, but reduces redundancy if a top team patches it round 1.
- README is terser than svc2's docs set.

---

## svc4-nanofleet — **8.0 / 10** (at ECSC baseline) — was 4.8

**Stack:** Go + `net/http`, JSON-on-disk state, single container, port 8080. ~830 LOC service (was 549).

### Vuln Design — 8/10 (was 6)
Three independent vulnerabilities across three flagstores:

- **FS0 / VULN-A (primary):** route shadowing via `diag;read:<node>` — the original anti-AI bug, still the headline. Authorization checks the prefix; the executor walks the whole `;`-delimited chain.
- **FS0 / VULN-B (exercise):** legacy `/api/tlv/decode?length=260` magic-value telemetry dump.
- **FS0 / VULN-C (exercise):** legacy `/api/firmware/blob/<b>?manifest=public` plaintext override.
- **FS1 / VULN-D:** **firmware-manifest signature binding** — the HMAC binds `{blob, ttl}` but the read handler honors unsigned `?reveal=1` and `?blob=` query parameters. A public manifest token unlocks every blob in the fleet. Same anti-AI category as svc3's download-actor bug, but in an IoT/firmware domain.
- **FS2 / VULN-E:** **JWT-like diagnostic token KID/alg confusion** — the verifier accepts `alg=KID` and resolves the kid against the registered-agent table, using that agent's `blob` field as the HMAC key. Because `/api/v2/agent/register` returns the registering caller's own blob, anyone can mint a KID-signed token for any payload.node. A clean kid-injection bug; the family is real-world (CVE-shaped) but the mechanism here is original.

Five vulnerabilities, three independent categories (parser confusion, signature binding, alg/kid confusion), no rabbit holes confused with legit bugs. Comparable to svc3 (8/10) and Gitter (8/10).

### Realism — 7/10 (was 5)
The codebase grew from a stub to a layered Go service with `internal/{state,routes,firmware,jobs,token,eno,ops,ui,tlv}` packages, three independent token systems, an agent registry, and persisted JSON state. Still single-container, still JSON-on-disk rather than SQLite, so it doesn't reach svc1's 8/10 — but the architecture is now legitimately production-shaped. The IoT/drone-fleet premise is plausible and the route/firmware/job vocabulary feels lived-in.

### Checker — 8/10 (was 5)
Now follows the svc1–3 pattern: sync wrapper (`checker/checker.py`) + async `enochecker3` app (`checker/src/{checker,client,gunicorn.conf}.py` with `pyproject.toml`). 3 putflag/getflag pairs, 3 putnoise/getnoise pairs, **6 HAVOC variants** exercising the route, register/schedule, firmware, ops/jwt-inspect, and node-catalog surfaces. `service.json` declares the `checker` block alongside ECSC norms. Comparable to svc3's 738-LOC checker on coverage shape; somewhat lighter on chain-of-trust depth.

### Ops — 9/10 (was 3)
**5 named patches** (`patches/flagstore-{0,1,2}/vuln-{a..e}-*.patch`), all of which apply cleanly via `patch -p1`, build under `go build`, preserve the SLA, and block their respective exploit (verified end-to-end). CI workflow at `.github/workflows/ci.yml` runs build → service-boot → sync-checker → exploit-matrix → patch-matrix (per-patch isolated SLA assertion). Three docs: `docs/{architecture,runbook,threat-model}.md`. Three named exploits (`exp1`/`exp2`/`exp3.py`) plus a refreshed `solver.py` that drives all three via the feed control plane.

Now matches svc1 on patch hygiene. **Above** Jitterish/Gitter/Heavensent (which ship zero patches).

### Why not 9 overall
- Single-container Go with JSON-on-disk is still lighter than Rust+SQLite-WAL (svc1) or polyglot C++/Rust/Go (svc2).
- The three vuln categories are sound but don't reach Heavensent-level conceptual originality.

---

## svc5-policyforge — **7.8 / 10** (at ECSC baseline) — was 4.8

**Stack:** Elixir + Plug + Cowboy, Erlang-term persistence on disk, single container, port 8080. ~570 LOC across 9 lib modules (was 420 across 7).

### Vuln Design — 8/10 (was 6)
Five vulnerabilities across three flagstores:

- **FS0 / VULN-A (primary):** ABAC **decision-cache key collision** — cache keyed by `user:tenant:class`, so a positive `allow` warmed on the public incident reuses for a private incident of the same class. The strongest concept in the platform set — real-world authorization-cache flaw, semantically subtle, LLM-grep-proof.
- **FS0 / VULN-B (exercise):** `/api/policy/eval?expr=allow public::<id>` returns the full object including `data`.
- **FS0 / VULN-C (exercise):** `/api/snapshot/<s>/object/<id>?tenant=public` accepts unsigned tenant claim.
- **FS1 / VULN-D:** **share-token signature scope mismatch** — the share token's HMAC binds the snapshot id only; the read handler dereferences an unsigned `:id` URL parameter. A token minted for `public-snap` reads every object in the store. Same anti-AI category as svc3's unsigned-actor and svc4's `?reveal=1`, expressed in snapshot-export terms.
- **FS2 / VULN-E:** policy DSL **`unless` keyword bypasses the `private::` substring denylist** by routing inner expressions through a `raw_eval/1` helper. The bug shape — "one parser branch trusts caller-supplied content that another branch denylists" — is exactly the class of DSL/policy-engine bug that ships in production authorization engines (looking at OPA history). Original phrasing.

Three independent categories (cache-key under-specification, signature binding, DSL parser-branch bypass). Per-variant object class (`incident` / `ledger-share` / `audit-record`) ensures the cache-collision bug only leaks variant 0, so primary surfaces don't accidentally cross-reach.

### Realism — 6/10 (was 5)
Still the lightest service by LOC, but now with structured separation: `share.ex` token module, public-snapshot seeding, multi-branch DSL with explicit `raw_eval` helper, Erlang-term persistence with deterministic restore. Elixir/OTP application with proper supervisor tree. Doesn't reach svc4's 7 because the surface area is genuinely smaller (no agent registry, no scheduling, no firmware) — but as a focused policy engine it's now coherent rather than stubby.

### Checker — 8/10 (was 5)
Modular `enochecker3` app same shape as svc4. 3 putflag/getflag pairs, 3 noisestores, **6 HAVOC variants** exercising health, session, objects, policy.eval (allow public + private denylist), share-token issuance, snapshot reads. `service.json` declares the `checker` block.

### Ops — 9/10 (was 3)
**5 named patches** that all apply, all docker-build, all preserve SLA, and all block their respective exploit (verified). CI workflow with exploit-matrix + per-patch SLA matrix. Three docs: `docs/{architecture,runbook,threat-model}.md`. `exp1`/`exp2`/`exp3.py` + refreshed `solver.py`.

### Why slightly below svc4
- Smaller LOC footprint and narrower surface area (no register/schedule/firmware subsystems).
- Two of the three vulns (D and E) live in the same Elixir module pair (router + policy_dsl); svc4 spreads its vulns across three independent modules (`routes`, `firmware/manifest`, `jobs`).

---

## Cross-cutting observations

### Where the platform set beats ECSC
- **Patch hygiene across all five.** 5 named patches per service with structured filenames, every patch verified to apply, build, and preserve SLA via `patch -p1` + CI matrix. **Jitterish, Gitter, and Heavensent ship zero patches**; only Firewall matches this. The platform set now leads on production readiness across the board, not just svc1–3.
- **CI/patch validation across all five.** Every svc has `.github/workflows/ci.yml` running build → checker → exploit-matrix → per-patch SLA matrix. ECSC services rely on `enochecker_test.yml` only.
- **Crypto and DSL pedagogy.** svc2's CBC padding oracle, svc1's SHA-256 length extension, and svc5's DSL `unless` bypass are all more transferable lessons than Jitterish's JIT-symbol override.

### Where ECSC still leads
- **Originality of premise.** Heavensent (satellite/SDR) and Jitterish (cloud storage with JIT-compiled queries) sit at a level of conceptual originality nothing in svc1–5 reaches. svc2's polyglot storage system is the closest.
- **Architectural depth.** Firewall's 5-container VPN/FTP/SNMP/Postgres topology is the most realistic A/D service in either set.
- **Exotic stack risk-taking.** AngelScript bytecode (Heavensent) and a custom C++ JIT (Jitterish) commit to harder reverse-engineering surfaces than any platform svc.

### What changed in this re-rating
svc4 and svc5 each gained two new flagstores' worth of vuln surface (firmware-manifest signature binding + JWT KID confusion for svc4; share-token sig binding + DSL `unless` bypass for svc5), modular `enochecker3` checkers with 6 HAVOC variants each, five named patches each, CI workflows with exploit/patch matrices, and three docs each (architecture/runbook/threat-model). End-to-end smoke confirms: checker OK on unpatched and on each patch applied, all three exploits leak on unpatched, all three blocked on patched. svc1–3 scores are unchanged.

---

## Prioritized recommendations

1. **Backfill svc1/svc2 metadata consistency.** Pre-existing mismatches in `tests/unit/test_challenge_pack_contract.py` (svc1's `rabbit_holes` expected 5 but meta is 3; svc2's runtime string drifted to `polyglot-cpp20-rust-go`) need either meta or test updates. Not blocking; just clean-up.
2. **Add an architecture/runbook doc to svc1 and svc3** to match svc2's documentation depth.
3. **Grow svc2's checker** — it's the smallest in the platform set despite the most complex topology.
4. **Consider one more "exotic" service** — something with the conceptual originality of Heavensent (e.g., a custom VM, a hardware/firmware simulator, an SDR/MQTT/IoT-protocol service) — to give the platform set a top-of-difficulty anchor that beats svc2 on premise.
