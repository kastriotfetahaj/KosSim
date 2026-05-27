from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_platform_validator_passes() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_platform.py")],
        cwd=ROOT,
        check=True,
    )


def test_static_platform_smoke_passes() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "smoke_platform.py"), "--team-count", "2"],
        cwd=ROOT,
        check=True,
    )
