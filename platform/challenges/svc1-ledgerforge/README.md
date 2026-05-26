# LedgerForge

Merkle-backed document ledger with scoped read capabilities, signed settlement
vouchers, and a treasury receipts vault. Analysts log in, commit branches,
fetch signed grants for public reads, mint short-lived viewer tokens for
settlements, and register scoped viewer keys for treasury receipts.

Three flagstores, each behind a distinct primitive. Tests, the sync checker,
and the async (`enochecker3`) checker all live in this tree.

## Layout

```
service/      Rust + axum app (the SUT)
  src/        routes, accounts, settlements, treasury, policies, admin, indexer
  static/     SPA
  tests/      cargo integration tests
checker/
  checker.py  sync entry point used by the KosSim platform driver
  src/        enochecker3 async app (gunicorn + uvicorn)
exploits/     one independent exploit per flagstore
patches/      patches that close each intended vulnerability
meta/         service metadata
```

## Running locally

```sh
cd service
SERVICE_PUSH_SECRET=dev-secret-32-bytes-padding-hellllo \
TEAM_NAME=local \
SERVICE_NAME=svc1 \
BOOT_FLAG=FLAG{LOCAL_BOOT} \
LEDGERFORGE_DATA_DIR=$(mktemp -d) \
cargo run --release
```

Visit `http://127.0.0.1:8080/`.

## Running the checker

Sync (the KosSim platform driver speaks this one):

```sh
SERVICE_PUSH_SECRET=dev-secret-32-bytes-padding-hellllo \
  python3 checker/checker.py http://127.0.0.1:8080
```

Async (ECSC-style, `enochecker3`):

```sh
cd checker/src
uv pip install -r <(uv pip compile pyproject.toml)
SERVICE_PUSH_SECRET=dev-secret-32-bytes-padding-hellllo \
  gunicorn -c gunicorn.conf.py checker:app
```

Then POST tasks to `http://127.0.0.1:8500` per the `enochecker3` API.

## Tests

```sh
cd service
cargo test
cargo check --all-targets
```

CI runs cargo + the sync checker against a Docker-built service, drives all
three exploits against the unpatched build, then re-runs the checker against
the patched build for every patch in `patches/**`.

## Threat model

- Untrusted: any unauthenticated HTTP caller; any caller holding only the
  values surfaced via attack-info (a doc id, a settlement id and its public
  viewer token, a treasury receipt id and the public viewer key).
- Trusted: the checker (X-Checker-Secret header), the analyst who owns a
  case or commit, the admin role.
- The team running the service may patch the source. Patches must preserve
  the contract the checker depends on: PUTFLAG, GETFLAG, all HAVOC variants,
  and PUTNOISE/GETNOISE must keep returning OK.

## Persistence

State is a SQLite file at `${LEDGERFORGE_DATA_DIR}/state.db` (WAL mode). The
deployed compose mounts a per-team named volume at `/var/lib/ledgerforge`.
SIGTERM checkpoints the WAL before exit. A legacy `state.json` from earlier
versions is migrated into the SQLite tables on first boot.

## Intended vulnerabilities

<details>
<summary>SPOILERS - open only if you are not playing</summary>

| # | Flagstore | Bug | Where it lives | Patch |
|---|-----------|-----|----------------|-------|
| A | 0 - `wire-transfer` (`/vault/<id>` doc) | scope check on raw path while storage lookup uses canonical path; `/public/%2e%2e/vault/<id>` passes scope and loads from `/vault/<id>` | `service/src/routes.rs` read_doc + `ledger::normalize_path` | `patches/flagstore-0/vuln-a-canonicalization.patch` |
| B | 0 - `wire-transfer` | snapshot export accepts `?claim=public:<doc_id>` as authorisation, bypassing the `public_label == "boot-public"` gate | `service/src/routes.rs` snapshot_export | `patches/flagstore-0/vuln-b-snapshot-claim-prefix.patch` |
| C | 0 - `wire-transfer` | LFQL `LOAD:public::<doc_id>` looks up by id in the global doc map without checking `doc.public` | `service/src/query.rs` execute | `patches/flagstore-0/vuln-c-lfql-load-public-bypass.patch` |
| D | 1 - `settlement-note` | viewer token uses raw `sha256(secret \|\| "\|" \|\| id \|\| "\|" \|\| viewer_bytes)`. Length extension lets the holder of a public-viewer token forge one whose comma-split scope contains `admin`, which unlocks the body | `service/src/crypto.rs` `sign_settlement_token` + `service/src/settlements.rs` viewer handler | `patches/flagstore-1/vuln-d-length-extension.patch` |
| E | 2 - `treasury-key` (receipt body) | `check_scope` treats an empty scope set as universal access. The seeded `public-viewer` key has `scopes=[]`, so it reads receipts of any scope | `service/src/treasury.rs` `check_scope` | `patches/flagstore-2/vuln-e-empty-scope-universal.patch` |

Each exploit script in `exploits/` targets one bug and one flagstore. VULNs
B and C remain in the code as redundant paths to flagstore 0 and are not
re-exploited; their patches still ship so they can be closed independently.

Attack-info schemas:

```
flagstore 0: {"a": doc_id, "b": snap_id, "c": class, "d": "guest-mirror",
              "t": tick, "p": 0}
flagstore 1: {"a": settlement_id, "b": "public", "token": hex64, "t": tick, "p": 1}
flagstore 2: {"a": receipt_id, "b": "public-viewer", "t": tick, "p": 2}
```

The grant HMAC key in this version is `HMAC(SERVICE_PUSH_SECRET,
"grant-key:<team>:<service>")` (an earlier base used a public key string,
which let anyone forge grants). The proof endpoint returns only the merkle
path, not the leaf body. The CLI commit endpoint requires an analyst
session.

</details>
