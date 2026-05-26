# KosSim Attack/Defense Platform

> **KosSim Documentation** — this documentation explains both **what** each platform element does and **why** it exists for a fair, repeatable attack/defense competition.

`Round-based game` · `Docker local test` · `Hetzner IaC` · `VPN access` · `NAT source masking`

## Quick Navigation

- [Overview](README.md)
- [Architecture](docs/architecture.html)
- [Challenges](docs/challenges.html)
- [Data Schema](docs/schema.html)
- [Local Runbook](docs/local-runbook.html)
- [Hetzner Runbook](docs/hetzner-runbook.html)

## At a Glance

| Metric | Detail |
| --- | --- |
| **5 Services / Team** | Balanced attack surface across all teams |
| **Configurable Tick** | Local default is 120s; deployments can set `ROTATION_SECONDS` |
| **Attack/Defense Scoring** | Service score is attack plus defense, multiplied by SLA |

## Core Elements: What and Why

| Element | What It Does | Why It Is Needed |
| --- | --- | --- |
| Scoring API + Leaderboard | Shows attack, defense, uptime, and total points in real time. | Gives teams immediate feedback and removes ambiguity about match state. |
| Flag Submit API | Accepts scripted submissions with team tokens. | Allows automation and equal speed for all teams. |
| Flag Rotation (every 60s) | Regenerates active flags for every service of every team each tick. | Prevents replay abuse and keeps pressure on continuous exploitation. |
| 5 Challenges per Team | Deploys the same vulnerable service set to each team stack. | Ensures fairness and provides multiple exploit classes. |
| NOP Stack | Always-on service stack for smoke tests and validator checks. | Lets organizers test pipelines safely outside team scoring impact. |
| Shared Competition Network | Control plane, teams, and NOP communicate on one private network. | Required for rotator reachability, checker traffic, and realistic lateral paths. |
| NAT Egress per Team | Attack requests traverse team NAT gateway before reaching targets. | Targets see NAT source identity, not internal attacker container IP. |
| Team VPN Access | WireGuard profiles grant secure access to private competition subnet. | Keeps services private while allowing remote team participation. |
| IaC for Hetzner | Terraform creates control, team hosts, NOP, VPN, and network. | Enables repeatable deployments, rollback, and auditability for events. |

## Local Start

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

Open leaderboard at `http://localhost:8088/scoreboard` and score JSON at `http://localhost:8088/api/v1/scoreboard`.

Team1 auto-attack loop (team2 + team3):

```bash
python3 scripts/team1_attack_loop.py --targets team2,team3 --team-token submit-team1
```

Stop stack:

```bash
docker compose -f docker-compose.generated.yml down -v
```

## Scoring Logic

- Attack points use ECSC-style jeopardy scoring: a captured flag starts at `10` points and decays as more teams submit that same flag.
- Defense points reward teams whose flags remain retrievable across the retention window while other teams are compromised.
- SLA points are based on checker health and retained flag availability for each service.
- Leaderboard round number is user-friendly and increments `1, 2, 3, ...` each tick.
