"""Path setup so `platform.control.app.<module>` imports resolve.

The control plane lives under ``platform/control/app`` and uses relative
imports (``from .db import ...``) — meaning we have to import it as a
proper package, not just by sys.path-injecting the ``app`` directory.

We expose it under the synthetic name ``ksapp`` so test modules can write
``from ksapp.flag_crypto import ...`` without colliding with stdlib
``platform`` or causing FastAPI's app singleton to be instantiated for
tests that only need pure functions.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP_DIR = ROOT / "platform" / "control"


os.environ.setdefault("SECRET_FLAG_KEY", "test-secret-flag-key")
os.environ.setdefault("SERVICE_PUSH_SECRET", "test-service-push-secret")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("ADMIN_SESSION_SECRET", "test-admin-session-secret")
os.environ.setdefault("GAME_ADMIN_TOKEN", "test-game-admin-token")


def _install_alias() -> None:
    if "ksapp" in sys.modules:
        return
    # Add the parent of the `app` directory to sys.path, then import `app`
    # under a stable alias so relative imports inside it still work.
    sys.path.insert(0, str(APP_DIR))
    mod = importlib.import_module("app")
    sys.modules["ksapp"] = mod


_install_alias()
