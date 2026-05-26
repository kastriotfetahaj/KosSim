"""Cookie session authentication for the operator admin panel."""

from __future__ import annotations

import os
import secrets
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from .config import env_bool, required_env


def session_secret() -> str:
    return required_env("ADMIN_SESSION_SECRET")


def admin_username() -> str:
    return os.getenv("ADMIN_USERNAME", "admin")


def admin_password() -> str:
    return required_env("ADMIN_PASSWORD")


def install_session_middleware(app) -> None:
    app.add_middleware(
        SessionMiddleware,
        secret_key=session_secret(),
        session_cookie="kossim_admin",
        max_age=60 * 60 * 12,
        same_site="lax",
        https_only=env_bool("ADMIN_HTTPS_ONLY"),
    )


def verify_credentials(username: str, password: str) -> bool:
    return (
        secrets.compare_digest(username.strip(), admin_username())
        and secrets.compare_digest(password, admin_password())
    )


def is_authenticated(request: Request) -> bool:
    return bool(request.session.get("admin_user"))


def login_user(request: Request) -> None:
    request.session["admin_user"] = admin_username()


def logout_user(request: Request) -> None:
    request.session.clear()


def require_admin(request: Request) -> str:
    user = request.session.get("admin_user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return str(user)


def require_admin_or_redirect(request: Request) -> Optional[RedirectResponse]:
    if not is_authenticated(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    return None
