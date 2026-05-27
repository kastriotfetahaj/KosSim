[← README](../README.md) · [Architecture](architecture.md) · [Local Runbook](local-runbook.md) · [Production Hardening](production-hardening.md)

---

# Event Day Runbook

This is the operator checklist for running KosSim during a live attack/defense event.

## Pre-Event

1. Generate secrets in `.env` and keep `.env.example` unchanged.
2. Run `make setup` on the organizer machine.
3. Run `make verify` from a clean checkout.
4. Build the team topology:

```bash
python3 scripts/generate_compose.py --team-count <N> --output docker-compose.generated.yml
docker compose --env-file .env -f docker-compose.generated.yml config >/dev/null
```

5. Export sanitized team sources:

```bash
python3 scripts/export_team_challenges.py --out dist/team-challenges
```

6. Confirm every service has the expected three flagstores:

```bash
python3 scripts/validate_platform.py
```

## Start Sequence

1. Start the stack:

```bash
docker compose --env-file .env -f docker-compose.generated.yml up -d --build
```

2. Wait for control-plane health:

```bash
curl -fsS http://localhost:8088/health
```

3. Open the admin dashboard at `http://localhost:8088/admin`.
4. Check the Operator readiness band:
   - Database: `ok`
   - Redis: `ok`
   - Workers: at least one heartbeat
   - Queue depth: not growing continuously
   - Overdue jobs: `0`
5. Open `http://localhost:8088/public/scoreboard` and confirm all expected teams appear.

## Validation Sequence

Run one static smoke before teams connect:

```bash
python3 scripts/smoke_platform.py --team-count <N>
```

For a full local boot smoke on the event host:

```bash
python3 scripts/smoke_platform.py --team-count <N> --docker
```

Then verify active rotation:

```bash
curl -H "Authorization: Bearer $GAME_ADMIN_TOKEN" \
  http://localhost:8088/api/v1/flags/current/team1/svc1
```

## During the Event

Watch these pages:

- `/admin` for operator readiness and current tick state.
- `/admin/observability` for queue, worker, SLA, and checker failures.
- `/admin/checkers` for per-job traces.
- `/admin/submissions` for accepted/rejected flag flow.
- `/public/scoreboard` for the audience scoreboard.

Treat these as escalation signals:

- Redis unavailable.
- No checker worker heartbeat.
- Queue depth increasing for more than two ticks.
- Overdue checker jobs.
- Repeated checker crashes.
- Stale vulnbox reports.
- Scoreboard tick not advancing while the desired state is running.

## Freeze, Pause, and Stop

Use the admin Game page for normal operations.

Use freeze when scores must stop moving but public display should remain available. Use pause when rotation and checking should stop temporarily. Use stop only when the event is finished or a reset is required.

Before any destructive reset:

```bash
docker compose --env-file .env -f docker-compose.generated.yml logs --no-color > dist/event-logs.txt
```

## Reset

For a full local reset:

```bash
docker compose --env-file .env -f docker-compose.generated.yml down -v --remove-orphans
docker compose --env-file .env -f docker-compose.generated.yml up -d --build
```

After reset, repeat the validation sequence before letting teams resume.

## Post-Event

1. Freeze the scoreboard.
2. Export logs:

```bash
docker compose --env-file .env -f docker-compose.generated.yml logs --no-color > dist/event-logs.txt
```

3. Save the generated compose file, `.env` secret inventory location, exported team challenges, and scoreboard JSON.
4. Tear down only after exports are confirmed:

```bash
docker compose --env-file .env -f docker-compose.generated.yml down
```
