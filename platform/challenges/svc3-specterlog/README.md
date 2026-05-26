# SpecterLog

Incident-stream collector for a fictional SOC. Analysts file cases, attach
evidence (signed downloads), and write directive briefs that referenced
via short-lived view tokens. Public reviewers can replay the public event
stream with a signed cursor and browse published cases.

The service ships three flagstores, each reachable by an independent
exploit path. Tests, the sync checker, and the async (`enochecker3`)
checker all live in this tree.

## Layout

```
service/      Bun + Fastify TypeScript app (the SUT)
  src/        routes, accounts, cases, briefs, attachments, admin, indexer
  static/     SPA + CLI shell
  test/       bun:test unit tests
checker/
  checker.py  sync entrypoint used by the KosSim platform driver
  src/        enochecker3 async app (gunicorn + uvicorn)
exploits/     one independent exploit per flagstore
patches/      patches that close each intended vulnerability
meta/         service metadata
```

## Running locally

```sh
cd service
SERVICE_PUSH_SECRET=dev-secret \
TEAM_NAME=local \
SERVICE_NAME=svc3 \
BOOT_FLAG=FLAG{LOCAL_BOOT} \
SPECTERLOG_DATA_DIR=$(mktemp -d) \
SPECTERLOG_STATIC_DIR=$(pwd)/static \
bun src/main.ts
```

Visit `http://127.0.0.1:8080/`. The CLI shell at the top of the page talks
to the same JSON API as the checker.

## Running the checker

Sync (the KosSim platform driver speaks this one):

```sh
SERVICE_PUSH_SECRET=dev-secret python3 checker/checker.py http://127.0.0.1:8080
```

Async (ECSC-style, `enochecker3`):

```sh
cd checker/src
uv pip install -r <(uv pip compile pyproject.toml)
SERVICE_PUSH_SECRET=dev-secret \
  gunicorn -c gunicorn.conf.py checker:app
```

Then POST a task to `http://127.0.0.1:8500` per the `enochecker3` API.

## Tests

```sh
cd service
bun test          # bun:test unit suite (tokens, state, flagstores)
bun --bun tsc --noEmit
```

CI runs the bun test suite, builds the Docker image, runs the sync
checker against a live container, drives all three exploits against the
unpatched build, and then re-runs the checker against the patched build
for every patch in `patches/**` (SLA preservation contract).

## Threat model

- Untrusted: any unauthenticated HTTP caller; any caller holding only the
  values exposed via attack-info (a flag id, a handle, a signed URL).
- Trusted: the checker (X-Checker-Secret header), the analyst who owns a
  case/brief, the admin role.
- The team running the service may patch the source. Patches must
  preserve the contract the checker depends on: PUTFLAG, GETFLAG, all
  HAVOC variants, and PUTNOISE/GETNOISE must keep returning OK.

## Persistence

State is a SQLite file at `${SPECTERLOG_DATA_DIR}/state.db` (WAL mode).
Attachment blobs live under `${SPECTERLOG_DATA_DIR}/blobs/<prefix>/<handle>`.
The deployed compose mounts a per-team named volume at
`/var/lib/specterlog` so flags survive container restarts and image
rebuilds. SIGTERM checkpoints the WAL before exit.

## Intended vulnerabilities

<details>
<summary>SPOILERS — open only if you are not playing</summary>

| # | Flagstore | Bug | Where it lives | Patch |
|---|-----------|-----|----------------|-------|
| A | 0 — `incident` (private event stream) | `/api/replay?mode=delta&stream=…` overrides the stream after cursor verification and ORs `mode=delta` into the public predicate | `service/src/routes.ts` replay handler | `patches/flagstore-0/vuln-a-cursor-stream-override.patch` |
| B | 0 — `incident` | `/api/search?filter=public\|\|private&project=body` — `String.includes` substring is treated as an ACL grant; `project=body` then returns the raw event body | `service/src/routes.ts` search handler | `patches/flagstore-0/vuln-b-search-filter-substring.patch` |
| C | 0 — `incident` | `/api/archive/:archive?window=public:../private` — `String.startsWith` flag flip exposes private events; `/api/events` discloses archive ids for private rows | `service/src/routes.ts` events + archive handlers | `patches/flagstore-0/vuln-c-archive-window-startswith.patch` |
| D | 1 — `evidence` (attachment blob) | `signDownload` HMACs `case_id\|handle\|exp` and omits `actor`. The download handler reads `actor` from the unsigned querystring and serves the raw blob when `actor=admin`. Attack-info publishes a public-actor URL; swap actor to admin | `service/src/tokens.ts` + `attachments.ts` | `patches/flagstore-1/vuln-d-download-actor-unsigned.patch` |
| E | 2 — `directive` (brief) | `verifyView` parses a JOSE-style header and accepts `alg=none` (empty signature segment). Forge a token with `briefs:read` scope and the target `brief_id` | `service/src/tokens.ts` `verifyView` | `patches/flagstore-2/vuln-e-view-token-alg-none.patch` |

Each exploit script in `exploits/` targets one bug and one flagstore.
`exp1.py` uses VULN A; VULNs B and C remain in the code as redundant
paths to the same store and are left as exercises.

Attack-info schemas:

```
flagstore 0: {"a": event_id:int, "b": archive:str, "p": 0}
flagstore 1: {"a": case_id:str, "b": handle:str, "p": 1,
              "exp": int, "sig": hex, "actor": "public"}
flagstore 2: {"a": brief_id:str, "b": case_id:str, "p": 2}
```

</details>
