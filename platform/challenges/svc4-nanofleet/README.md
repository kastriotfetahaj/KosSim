# NanoFleet

NanoFleet is a single-container drone-telemetry orchestrator written in Go
(`net/http` + `encoding/json`). Players register agents, schedule jobs,
fetch signed firmware manifests, and run diagnostic routes against the
fleet. Three flagstores live behind three independent token systems.

## Flagstores

| Variant | Node kind     | Intended bug                                           |
|---------|---------------|--------------------------------------------------------|
| 0       | `secret`      | Route shadowing: `diag` token authorizes `diag;read:<id>` |
| 1       | `manifest`    | Firmware-manifest signature does not bind `?reveal=1` or `?blob=` |
| 2       | `diagnostic`  | Diagnostic JWT accepts `alg=KID` keyed off any agent's blob |

Two further legacy paths on flagstore 0 (`/api/tlv/decode?length=260` and
`/api/firmware/blob/<b>?manifest=public`) provide alternate extractors;
patching the primary surface without disabling these leaves the flag
exposed.

## Layout

- `service/` — Go service (`cmd/nanofleet`, `internal/{routes,state,
  firmware,jobs,token,eno,ops,ui,tlv}`).
- `checker/` — sync wrapper (`checker.py`) plus async enochecker3 app
  (`src/checker.py`, `src/client.py`).
- `exploits/` — one named exploit per flagstore (`exp1.py`, `exp2.py`,
  `exp3.py`) plus a round-driven `solver.py` for the production feed.
- `patches/` — five `.patch` files (one per vulnerability), organized by
  flagstore.
- `docs/` — architecture, runbook, threat model.
- `meta/service.json` — flagstore / noisestore / havoc-variant counts.

## Quick start

```sh
docker build -t nanofleet-service -f svc4-nanofleet/service/Dockerfile .
docker run --rm -p 8080:8080 \
  -e SERVICE_PUSH_SECRET=rotate-secret \
  -e TEAM_NAME=dev -e SERVICE_NAME=svc4 \
  nanofleet-service
python svc4-nanofleet/checker/checker.py http://127.0.0.1:8080
```

See `docs/runbook.md` for operating notes and `docs/architecture.md` for
the data model.
