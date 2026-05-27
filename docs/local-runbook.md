[← README](../README.md) · [Architecture](architecture.md) · [Challenges](challenges.md) · [Data Schema](schema.md) · [Local Runbook](local-runbook.md) · [Hetzner Runbook](hetzner-runbook.md)

---

# Local Runbook (Docker)

This runbook is for fast local testing of the full A/D lifecycle: rotate, attack, submit, score, and leaderboard refresh.

## Before You Start

| Requirement | Why It Is Needed |
| --- | --- |
| Docker + Docker Compose | Runs full control plane and all team services in one machine. |
| `python3` | Runs helper scripts for compose generation and attack automation. |

## Step-by-Step

### 1) Generate and Start Stack

**What:** Build compose file for 3 teams and start all components.

**Why:** You need multiple teams for real attack/defense scoring behavior.

```bash
export POSTGRES_PASSWORD="$(openssl rand -hex 16)"
export SERVICE_PUSH_SECRET="$(openssl rand -hex 32)"
export SECRET_FLAG_KEY="$(openssl rand -hex 32)"
export ADMIN_PASSWORD="$(openssl rand -base64 24)"
export ADMIN_SESSION_SECRET="$(openssl rand -hex 32)"
export GAME_ADMIN_TOKEN="$(openssl rand -hex 32)"
python3 scripts/generate_compose.py --team-count 3 --output docker-compose.generated.yml
docker compose -f docker-compose.generated.yml up -d --build
```

### 2) Verify Leaderboard and API

**What:** Open human dashboard and machine-readable JSON feed.

**Why:** Confirms control plane is healthy and scoring fields are available.

- `http://localhost:8088/scoreboard`
- `http://localhost:8088/api/v1/scoreboard`

Expected behavior: live countdown, automatic refresh at each tick reset, and round counter displayed as `1,2,3,...`. Local compose defaults to `ROTATION_SECONDS=120`.

### 3) Confirm Flag Rotation

**What:** Query current flag for one team/service before and after one tick.

**Why:** Validates per-round flag freshness.

```bash
curl -H "Authorization: Bearer $GAME_ADMIN_TOKEN" \
  http://localhost:8088/api/v1/flags/current/team2/svc1
sleep 125
curl -H "Authorization: Bearer $GAME_ADMIN_TOKEN" \
  http://localhost:8088/api/v1/flags/current/team2/svc1
```

### 4) Submit Flag by Script

**What:** Submit candidate flags with team token.

**Why:** Emulates real team automation clients.

```bash
python3 scripts/submit_flags.py \
  --endpoint http://localhost:8088/api/v1/flags/submit \
  --team-token submit-team1 \
  --flags FLAG{example}
```

### 5) NAT Source Identity (Hetzner)

**What:** On Hetzner each team host is a kernel NAT gateway (iptables `SNAT`/`MASQUERADE`), so all team-originated traffic toward the competition network presents the team's private IP for every protocol.

**Why:** Targets identify the attacking team's NAT source, not the internal container IP. Locally all teams share one Docker network and attacks reach services directly, so this masking applies to the Hetzner deployment.

### 6) Run Full Attack Loop (Team1 -> Team2, Team3)

**What:** Automatically hack targets and submit every tick.

**Why:** End-to-end simulation of competition behavior.

The reference attack script targets one team per loop — run one per target:

```bash
python3 scripts/team1_hack_team2.py --target team2 --team-token submit-team1
python3 scripts/team1_hack_team2.py --target team3 --team-token submit-team1
```

One-round test:

```bash
python3 scripts/team1_hack_team2.py --once --target team2
```

### 7) Stop and Clean

**What:** Tear down containers and volumes.

**Why:** Resets state for repeatable tests.

```bash
docker compose -f docker-compose.generated.yml down -v
```

## Scoring and Tick Notes

- Attack points are fixed per captured flag (base `10` divided by the number of flag stores for the service) and are cumulative — they never decay, and every team that captures a flag scores independently.
- Defense points reward teams whose flags remain retrievable across the retention window while other teams are compromised.
- SLA points are based on checker health and retained flag availability for each service.
- Accepted cap defaults to unlimited when `MAX_ACCEPTED_PER_TEAM_PER_ROUND=0`.

> **Hint:** If round appears high or unexpected, check `raw_round_id` and `first_round_id` in scoreboard JSON. Display round is computed for human readability.
