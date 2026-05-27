[← README](../README.md) · [Architecture](architecture.md) · [Event Day Runbook](event-day-runbook.md) · [Hetzner Runbook](hetzner-runbook.md)

---

# Production Hardening

This checklist captures the controls that should be in place before KosSim is used for a real event.

## Secrets

- Generate unique values for `POSTGRES_PASSWORD`, `SERVICE_PUSH_SECRET`, `SECRET_FLAG_KEY`, `ADMIN_PASSWORD`, `ADMIN_SESSION_SECRET`, and `GAME_ADMIN_TOKEN`.
- Never commit `.env`.
- Rotate `GAME_ADMIN_TOKEN` after rehearsal events.
- Keep `SERVICE_PUSH_SECRET` unavailable to teams.

## Backups

Back up Postgres before the event, after rehearsal, before score freeze, and after the event:

```bash
docker compose --env-file .env -f docker-compose.generated.yml exec -T postgres \
  pg_dump -U kossim -d kossim > dist/kossim-backup.sql
```

Restore should be tested before event day:

```bash
docker compose --env-file .env -f docker-compose.generated.yml exec -T postgres \
  psql -U kossim -d kossim < dist/kossim-backup.sql
```

## Resource Limits

- Keep per-service `mem_limit` and `cpus` set in compose.
- Raise `CHECKER_CONCURRENCY` only after observing worker queue depth.
- Keep challenge persistence on named volumes.
- Keep NOP services enabled for baseline checker validation.

## Network Boundaries

- Expose only the control plane, TCP flag submission port, and intended team access paths.
- Keep service-to-service traffic on the private competition network.
- For Hetzner deployments, verify team NAT source identity before the event.
- Keep `/admin` behind trusted access where possible.

## Rate Limits

- Use `MAX_ACCEPTED_PER_TEAM_PER_ROUND` when the event format requires a cap.
- Monitor rejected submissions for automation loops or malformed clients.
- Watch queue depth during first attack bursts and reduce checker concurrency only if service health becomes noisy.

## Observability

The admin dashboard and `/admin/observability` should stay open during the event. Prometheus-compatible metrics are exposed through the control plane and include:

- `kossim_queue_depth`
- `kossim_queue_total`
- `kossim_checker_jobs`
- `kossim_worker_count`
- `kossim_overdue_checker_jobs`
- `kossim_stale_vulnboxes`
- `kossim_alerts`

Alert immediately on:

- Redis unavailable.
- Worker count at `0`.
- Overdue checker jobs greater than `0`.
- Repeated crashed jobs.
- Queue depth growing across multiple ticks.

## Admin Audit

Use `/admin/logs` as the operational timeline. Before resets or disputes, export container logs and preserve the database backup. Admin actions should be recorded with time, operator, reason, and expected impact in the event notes.

## Verification Gates

Before opening the event:

```bash
make verify
python3 scripts/smoke_platform.py --team-count <N>
```

For a full host-level validation:

```bash
python3 scripts/smoke_platform.py --team-count <N> --docker
```

Do not start the event with failing platform validation, missing checker workers, or red operator readiness.
