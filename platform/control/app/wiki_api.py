"""Team-facing wiki backed by simple markdown pages stored in Postgres.

Admins author pages by slug; teams and spectators read them. No revision
history — last write wins. The slug is the URL key and is normalised to
lowercase kebab-case on write.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .admin_auth import require_admin
from .db import get_cursor
from .event_log import LogLevel, write_log


_SCHEMA = """
CREATE TABLE IF NOT EXISTS wiki_pages (
    id BIGSERIAL PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    body_md TEXT NOT NULL DEFAULT '',
    is_published BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 100,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_wiki_published ON wiki_pages(is_published, sort_order, slug);
"""


_SLUG_OK = re.compile(r"^[a-z0-9][a-z0-9\-]{0,63}$")


DEFAULT_WIKI_PAGES = [
    {
        "slug": "ad-rules",
        "title": "Attack/Defense Rules",
        "sort_order": 10,
        "body_md": """# Attack/Defense Rules

KosSim is a round-based attack/defense game. Every team receives the same vulnerable services, keeps its own services alive, attacks other teams, and submits recovered flags to the control plane.

## Round flow

- The game advances in ticks. Local deployments use `ROTATION_SECONDS` from the environment.
- At the start of each tick, the platform creates fresh flags for every team service.
- Checkers validate each service with PUTFLAG, GETFLAG, and service-specific behavior checks.
- Teams exploit opponent services, recover flags, and submit them before they expire.
- Scores are calculated from the previous scored tick once checker jobs finish.

## What teams should do

- Keep all services reachable and functional throughout the game.
- Patch vulnerabilities without breaking the checker contract.
- Attack only opponent team services and submit valid opponent flags.
- Automate exploit runs and submissions; manual play is usually too slow.
- Watch the public scoreboard and team endpoints for live status.

## What does not score

- Submitting your own flag.
- Submitting NOP flags.
- Submitting expired or future flags.
- Submitting the same flag twice from the same team.
- Submitting while the game is stopped.

## Fairness model

Each team has the same service set and flagstore layout. NOP services exist for platform validation and smoke tests; they are not a scoring target.
""",
    },
    {
        "slug": "scoring-formula",
        "title": "Scoring Formula",
        "sort_order": 20,
        "body_md": """# Scoring Formula

KosSim uses positive scoring. Attack and defense points are cumulative, and SLA acts as a multiplier.

```text
service_score = attack_points + defense_points
service_total = service_score * sla_points
team_total = sum(service_total for every service)
```

## Attack points

Attack points are awarded for accepted opponent flags.

```text
attack_points_per_flag = 10 / flags_per_tick_for_service
```

If a service stores multiple flags per tick, each individual flag is worth a smaller share so the service remains balanced.

## Defense points

Defense rewards teams whose service is alive and whose flags were not stolen during the scored tick.

```text
defense_points_per_tick = 5 * flags_per_tick_for_service
```

Defense points for a service are skipped for that tick if the service was hacked or the checker health for that service is zero.

## SLA multiplier

`sla_points` is the running average service-health multiplier for that service.

- `SUCCESS` gives `1.0` for the tick.
- `RECOVERING` gives partial credit based on retained GETFLAG availability.
- `OFFLINE`, `MUMBLE`, and unrecoverable flag failures give `0.0`.

## Important details

- Attack and defense totals never decay.
- The scoreboard total can still move less than raw attack/defense changes because SLA multiplies the service score.
- The public scoreboard is frozen when operators configure a freeze tick.
- First blood is tracked for visibility, but normal accepted flags carry the point value.
""",
    },
    {
        "slug": "flag-submitter",
        "title": "Flag Submitter Usage",
        "sort_order": 30,
        "body_md": """# Flag Submitter Usage

Teams submit flags through the ECSC-style TCP submitter on port `1337`.

## TCP endpoint

Default endpoint:

```text
127.0.0.1:1337
```

## Submit format

Send your team token on one line, then the flag on the next line.

```bash
printf 'submit-team1\\nFLAG{example}\\n' | nc 127.0.0.1 1337
```

If the platform maps your source IP to a team, you can submit a flag directly:

```bash
printf 'FLAG{example}\\n' | nc 127.0.0.1 1337
```

## Responses

The submitter returns one line per submitted flag:

- `[OK]`
- `[ERR] Already submitted`
- `[ERR] Expired`
- `[ERR] This is your own flag`
- `[ERR] Invalid flag`
- `[OFFLINE] CTF not running`

## Submit tokens

Local defaults use `submit-<team_name>`, for example `submit-team1`. Operators can rotate tokens from the admin Teams page. Treat the token as a team secret.

## Practical automation

- Pull targets and flag IDs from `/api/attack.json`.
- Keep one TCP connection open when your submitter supports it.
- Submit each recovered flag as soon as possible; flags expire after the retention window.
- Deduplicate flags client-side before submitting.
- Treat non-`[OK]` responses as useful telemetry for exploit timing and target selection.
""",
    },
    {
        "slug": "team-api-reference",
        "title": "Team API Reference",
        "sort_order": 40,
        "body_md": """# Team API Reference

These endpoints are useful for teams and tooling during local practice or a live event.

## Scoreboard

```text
GET /public/scoreboard
GET /api/v1/scoreboard
```

The public scoreboard is the main spectator view. The JSON endpoint exposes rows, service cells, totals, tick metadata, and recent first-blood activity.

## Attack data

```text
GET /api/attack.json
GET /api/teams.json
GET /api/v1/attack_info
```

`/api/attack.json` is the main automation feed. It includes current tick metadata, service targets, the flag regex, and attack info grouped by service and team.

## Wiki

```text
GET /wiki
GET /api/v1/wiki
GET /api/v1/wiki/{slug}
```

The browser wiki is for humans. The JSON wiki endpoints are useful for mirroring rules into team tooling or a local terminal dashboard.
""",
    },
    {
        "slug": "event-checklist",
        "title": "Event Checklist",
        "sort_order": 50,
        "body_md": """# Event Checklist

Use this checklist before a practice game or live event starts.

## Before start

- Confirm every team appears on `/public/scoreboard`.
- Confirm all services are healthy in the admin Services or Observability views.
- Confirm team submit tokens have been distributed privately.
- Confirm teams can reach the control API and the TCP submitter.
- Confirm teams know the tick length and flag retention window.

## During game

- Watch checker failures and queue health.
- Watch submissions for invalid-token, own-flag, expired, or duplicate spikes.
- Keep the scoreboard visible for participants and spectators.
- Use freeze only when scores should stop moving while the display remains public.

## After game

- Export scoreboard JSON.
- Export submissions and checker failures for review.
- Keep final scoreboard visible or publish the exported standings.
""",
    },
]


def bootstrap_wiki_table() -> None:
    with get_cursor(commit=True) as (_conn, cur):
        cur.execute(_SCHEMA)
        for page in DEFAULT_WIKI_PAGES:
            cur.execute(
                """
                INSERT INTO wiki_pages (slug, title, body_md, is_published, sort_order)
                VALUES (%s, %s, %s, TRUE, %s)
                ON CONFLICT (slug) DO NOTHING;
                """,
                (page["slug"], page["title"], page["body_md"], page["sort_order"]),
            )


def _normalize_slug(raw: str) -> str:
    s = raw.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:64]


def _row(row: Dict[str, Any], *, include_body: bool = True) -> Dict[str, Any]:
    out = {
        "id": int(row["id"]),
        "slug": row["slug"],
        "title": row["title"],
        "is_published": bool(row["is_published"]),
        "sort_order": int(row["sort_order"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }
    if include_body:
        out["body_md"] = row["body_md"] or ""
    return out


# ---------------------------------------------------------------------------
# Public (team) endpoints
# ---------------------------------------------------------------------------


def build_public_wiki_router() -> APIRouter:
    router = APIRouter(tags=["wiki"])

    @router.get("/api/v1/wiki")
    def list_pages() -> Dict[str, Any]:
        with get_cursor(commit=False) as (_conn, cur):
            cur.execute(
                """
                SELECT id, slug, title, is_published, sort_order, created_at, updated_at
                FROM wiki_pages
                WHERE is_published = TRUE
                ORDER BY sort_order ASC, title ASC;
                """
            )
            rows = [_row(r, include_body=False) for r in cur.fetchall()]
        return {"rows": rows}

    @router.get("/api/v1/wiki/{slug}")
    def get_page(slug: str) -> Dict[str, Any]:
        with get_cursor(commit=False) as (_conn, cur):
            cur.execute(
                """
                SELECT id, slug, title, body_md, is_published, sort_order,
                       created_at, updated_at
                FROM wiki_pages
                WHERE slug = %s AND is_published = TRUE;
                """,
                (slug,),
            )
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="page not found")
        return _row(row)

    return router


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


admin_router = APIRouter(prefix="/admin/api/wiki", tags=["admin-wiki"])


class PageUpsert(BaseModel):
    slug: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    body_md: str = Field(default="", max_length=200_000)
    is_published: bool = True
    sort_order: int = 100


@admin_router.get("")
def admin_list(_: str = Depends(require_admin)) -> Dict[str, Any]:
    with get_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """
            SELECT id, slug, title, body_md, is_published, sort_order,
                   created_at, updated_at
            FROM wiki_pages
            ORDER BY sort_order ASC, title ASC;
            """
        )
        rows = [_row(r) for r in cur.fetchall()]
    return {"rows": rows}


@admin_router.get("/{slug}")
def admin_get(slug: str, _: str = Depends(require_admin)) -> Dict[str, Any]:
    with get_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """
            SELECT id, slug, title, body_md, is_published, sort_order,
                   created_at, updated_at
            FROM wiki_pages WHERE slug = %s;
            """,
            (slug,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="page not found")
    return _row(row)


@admin_router.post("")
def admin_upsert(body: PageUpsert, _: str = Depends(require_admin)) -> Dict[str, Any]:
    slug = _normalize_slug(body.slug)
    if not _SLUG_OK.match(slug):
        raise HTTPException(status_code=400, detail="invalid slug")
    with get_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """
            INSERT INTO wiki_pages (slug, title, body_md, is_published, sort_order)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (slug) DO UPDATE SET
                title = EXCLUDED.title,
                body_md = EXCLUDED.body_md,
                is_published = EXCLUDED.is_published,
                sort_order = EXCLUDED.sort_order,
                updated_at = NOW()
            RETURNING id, slug, title, body_md, is_published, sort_order,
                      created_at, updated_at;
            """,
            (slug, body.title, body.body_md, body.is_published, body.sort_order),
        )
        row = cur.fetchone()
    write_log(
        "wiki",
        f"Wiki page upserted: {slug}",
        body.title,
        level=LogLevel.INFO,
    )
    return _row(row)


@admin_router.delete("/{slug}")
def admin_delete(slug: str, _: str = Depends(require_admin)) -> Dict[str, Any]:
    with get_cursor(commit=True) as (_conn, cur):
        cur.execute(
            "DELETE FROM wiki_pages WHERE slug = %s RETURNING title;",
            (slug,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="page not found")
    write_log("wiki", f"Wiki page deleted: {slug}", row["title"], level=LogLevel.WARNING)
    return {"ok": True, "deleted_slug": slug}
