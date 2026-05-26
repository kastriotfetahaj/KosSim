"""Patch distribution endpoints.

Admins upload patch bundles (tarballs, ansible playbooks, raw text) per
service. Teams hit the public list/download endpoints to pull whatever has
been released so far. Bundles live in the DB so the control plane stays
stateless w.r.t. disk volumes.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from .admin_auth import require_admin
from .db import get_cursor
from .event_log import LogLevel, write_log


_SCHEMA = """
CREATE TABLE IF NOT EXISTS patches (
    id BIGSERIAL PRIMARY KEY,
    service_id INTEGER REFERENCES services(id) ON DELETE SET NULL,
    service_name TEXT NOT NULL,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    notes TEXT NOT NULL DEFAULT '',
    sha256 TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    blob BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_patches_service ON patches(service_name, created_at DESC);
"""


def bootstrap_patches_table() -> None:
    with get_cursor(commit=True) as (_conn, cur):
        cur.execute(_SCHEMA)


def _row_meta(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": int(row["id"]),
        "service_id": int(row["service_id"]) if row["service_id"] is not None else None,
        "service_name": row["service_name"],
        "filename": row["filename"],
        "content_type": row["content_type"],
        "notes": row["notes"] or "",
        "sha256": row["sha256"],
        "size_bytes": int(row["size_bytes"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


# ---------------------------------------------------------------------------
# Public (team) endpoints
# ---------------------------------------------------------------------------


def build_public_patches_router() -> APIRouter:
    router = APIRouter(tags=["patches"])

    @router.get("/api/v1/patches")
    def list_patches(service: Optional[str] = None) -> Dict[str, Any]:
        where: List[str] = []
        args: List[Any] = []
        if service:
            where.append("service_name = %s")
            args.append(service)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        with get_cursor(commit=False) as (_conn, cur):
            cur.execute(
                f"""
                SELECT id, service_id, service_name, filename, content_type,
                       notes, sha256, size_bytes, created_at
                FROM patches
                {where_sql}
                ORDER BY created_at DESC, id DESC;
                """,
                args,
            )
            rows = [_row_meta(r) for r in cur.fetchall()]
        return {"rows": rows}

    @router.get("/api/v1/patches/{patch_id}/download")
    def download_patch(patch_id: int) -> Response:
        with get_cursor(commit=False) as (_conn, cur):
            cur.execute(
                """
                SELECT filename, content_type, blob
                FROM patches WHERE id = %s;
                """,
                (patch_id,),
            )
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="patch not found")
        blob = bytes(row["blob"])
        return Response(
            content=blob,
            media_type=row["content_type"] or "application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{row["filename"]}"',
                "Content-Length": str(len(blob)),
            },
        )

    return router


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


admin_router = APIRouter(prefix="/admin/api/patches", tags=["admin-patches"])


@admin_router.get("")
def admin_list(_: str = Depends(require_admin)) -> Dict[str, Any]:
    with get_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """
            SELECT id, service_id, service_name, filename, content_type,
                   notes, sha256, size_bytes, created_at
            FROM patches
            ORDER BY created_at DESC, id DESC;
            """
        )
        rows = [_row_meta(r) for r in cur.fetchall()]
        cur.execute("SELECT id, name FROM services ORDER BY name;")
        services = [{"id": int(r["id"]), "name": r["name"]} for r in cur.fetchall()]
    return {"rows": rows, "services": services}


@admin_router.post("")
async def admin_upload(
    file: UploadFile = File(...),
    service_name: str = Form(...),
    notes: str = Form(""),
    _: str = Depends(require_admin),
) -> Dict[str, Any]:
    if not service_name.strip():
        raise HTTPException(status_code=400, detail="service_name required")
    blob = await file.read()
    if not blob:
        raise HTTPException(status_code=400, detail="empty upload")
    sha = hashlib.sha256(blob).hexdigest()
    filename = file.filename or "patch.bin"
    content_type = file.content_type or "application/octet-stream"
    with get_cursor(commit=True) as (_conn, cur):
        cur.execute(
            "SELECT id FROM services WHERE name = %s;", (service_name.strip(),)
        )
        sid_row = cur.fetchone()
        service_id = int(sid_row["id"]) if sid_row else None
        cur.execute(
            """
            INSERT INTO patches (service_id, service_name, filename, content_type,
                                 notes, sha256, size_bytes, blob)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, service_id, service_name, filename, content_type,
                      notes, sha256, size_bytes, created_at;
            """,
            (
                service_id,
                service_name.strip(),
                filename,
                content_type,
                notes or "",
                sha,
                len(blob),
                blob,
            ),
        )
        row = cur.fetchone()
    write_log(
        "patches",
        f"Patch uploaded for {service_name}",
        f"{filename} ({len(blob)} bytes, sha256={sha[:12]}…)",
        level=LogLevel.IMPORTANT,
    )
    return _row_meta(row)


class PatchNotesUpdate(BaseModel):
    notes: str = Field(max_length=4096)


@admin_router.patch("/{patch_id}")
def admin_update(
    patch_id: int,
    body: PatchNotesUpdate,
    _: str = Depends(require_admin),
) -> Dict[str, Any]:
    with get_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """
            UPDATE patches SET notes = %s
            WHERE id = %s
            RETURNING id, service_id, service_name, filename, content_type,
                      notes, sha256, size_bytes, created_at;
            """,
            (body.notes, patch_id),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="patch not found")
    return _row_meta(row)


@admin_router.delete("/{patch_id}")
def admin_delete(patch_id: int, _: str = Depends(require_admin)) -> Dict[str, Any]:
    with get_cursor(commit=True) as (_conn, cur):
        cur.execute("DELETE FROM patches WHERE id = %s RETURNING service_name, filename;", (patch_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="patch not found")
    write_log(
        "patches",
        f"Patch deleted for {row['service_name']}",
        row["filename"],
        level=LogLevel.WARNING,
    )
    return {"ok": True, "deleted_id": patch_id}
