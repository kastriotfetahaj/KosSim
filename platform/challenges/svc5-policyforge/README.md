# PolicyForge

PolicyForge is a single-container Elixir / Plug / Cowboy service that
simulates an ABAC policy engine for incident objects. Players warm
guest sessions, evaluate a small policy DSL, mint share tokens for
public snapshots, and read incident objects through several layered
APIs. Three flagstores live behind three independent token systems.

## Flagstores

| Variant | Object class    | Intended bug                                                  |
|---------|-----------------|---------------------------------------------------------------|
| 0       | `incident`      | Cache key `user:tenant:class` collides on same-class objects   |
| 1       | `ledger-share`  | Share token binds snapshot id but not the dereferenced object id |
| 2       | `audit-record`  | Policy DSL `unless` keyword bypasses the `private::` denylist |

Two further exercise paths on flagstore 0
(`/api/policy/eval?expr=allow public::<id>` and
`/api/snapshot/<snap>/object/<id>?tenant=public`) provide alternate
extractors; patching the primary cache bug without also closing these
leaves the flag exposed.

## Layout

- `service/` — Elixir/OTP application
  (`lib/policy_forge/{router,state,policy_dsl,snapshot,share,token,eno,ops,application}.ex`).
- `checker/` — sync wrapper (`checker.py`) plus async enochecker3 app
  (`src/checker.py`, `src/client.py`).
- `exploits/` — one named exploit per flagstore (`exp1.py`, `exp2.py`,
  `exp3.py`) plus a round-driven `solver.py` for the production feed.
- `patches/` — five `.patch` files (one per vulnerability), organized
  by flagstore.
- `docs/` — architecture, runbook, threat model.
- `meta/service.json` — flagstore / noisestore / havoc-variant counts.

## Quick start

```sh
docker build -t policyforge-service -f svc5-policyforge/service/Dockerfile .
docker run --rm -p 8080:8080 \
  -e SERVICE_PUSH_SECRET=rotate-secret \
  -e TEAM_NAME=dev -e SERVICE_NAME=svc5 \
  policyforge-service
python svc5-policyforge/checker/checker.py http://127.0.0.1:8080
```

See `docs/runbook.md` for operating notes and `docs/architecture.md` for
the data model.
