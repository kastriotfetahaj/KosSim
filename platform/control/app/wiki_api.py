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


def bootstrap_wiki_table() -> None:
    with get_cursor(commit=True) as (_conn, cur):
        cur.execute(_SCHEMA)


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
