from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICES = [
    ("svc1-ledgerforge", "ledgerforge"),
    ("svc2-vaultgrid", "vaultgrid"),
    ("svc3-specterlog", "specterlog"),
    ("svc4-nanofleet", "nanofleet"),
    ("svc5-policyforge", "policyforge"),
]


def main() -> int:
    base = os.environ.get("KOSSIM_CHECKER_BASE")
    for directory, name in SERVICES:
        checker = ROOT / "platform" / "challenges" / directory / "checker" / "checker.py"
        if not checker.exists():
            raise SystemExit(f"missing checker for {name}")
        text = checker.read_text()
        for required in ("PUTNOISE", "GETNOISE", "HAVOC"):
            common = ROOT / "platform" / "challenges" / "common" / "ecsc_checker.py"
            if required not in text and required not in common.read_text():
                raise SystemExit(f"{checker} lacks {required}")
        if base:
            subprocess.run([sys.executable, str(checker), base], check=True, cwd=ROOT)
    print("checker package ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
