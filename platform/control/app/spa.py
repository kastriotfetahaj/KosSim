from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def mount_spa(app: FastAPI) -> None:
    web_dist = Path(__file__).resolve().parent.parent / "web" / "dist"
    web_index = web_dist / "index.html"
    if not web_index.is_file():
        return

    app.mount(
        "/assets",
        StaticFiles(directory=str(web_dist / "assets")),
        name="spa-assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_catchall(full_path: str) -> FileResponse:
        candidate = web_dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(web_index))
