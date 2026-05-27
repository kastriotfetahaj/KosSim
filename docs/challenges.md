[← README](../README.md) · [Architecture](architecture.md) · [Challenges](challenges.md) · [Data Schema](schema.md) · [Local Runbook](local-runbook.md) · [Hetzner Runbook](hetzner-runbook.md)

---

# Challenge Pack (`svc1..svc5`)

All teams get the exact same service set. This keeps the game fair while testing different vulnerability categories.

## Shared Service Contract

| Endpoint | What It Does | Why It Exists |
| --- | --- | --- |
| `POST /internal/set_flag` | Sets current active flag in service state. Requires `X-Service-Secret`. | Allows central rotator to publish synchronized flags every tick. |
| `GET /health` | Returns service health status. | Feeds uptime scoring and operational checks. |
| `GET /whoami` | Returns request source details. | Used to verify NAT source identity behavior. |

## Service Roster

Every team runs the same five services in identical containers. Source code is published; vulnerability classes are not documented here.

| Service | Codename | Surface (cover story) |
| --- | --- | --- |
| `svc1` | LEDGERFORGE | Merkle-backed document ledger with scoped read capabilities. |
| `svc2` | VAULTGRID | Erasure-coded object vault with repair grants and shard recovery. |
| `svc3` | SPECTERLOG | Cursor-signed replay service for public and private event streams. |
| `svc4` | NANOFLEET | Drone telemetry orchestrator with signed diagnostic routes. |
| `svc5` | POLICYFORGE | ABAC policy engine for incident objects and cached decisions. |

### `svc1` LEDGERFORGE

**Path:** `platform/challenges/svc1-ledgerforge`

### `svc2` VAULTGRID

**Path:** `platform/challenges/svc2-vaultgrid`

### `svc3` SPECTERLOG

**Path:** `platform/challenges/svc3-specterlog`

### `svc4` NANOFLEET

**Path:** `platform/challenges/svc4-nanofleet`

### `svc5` POLICYFORGE

**Path:** `platform/challenges/svc5-policyforge`

### Why equal challenges

- Identical services remove hardware or challenge-diff bias.
- Score reflects exploitation and defense quality, not luck.
- Organizers can benchmark checker behavior uniformly.
