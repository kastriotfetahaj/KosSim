from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    for service in ("svc1", "svc2", "svc3", "svc4", "svc5"):
        patch_dir = ROOT / "organizer" / "patches" / service
        for name in ("vuln0.patch", "vuln1.patch", "all.patch"):
            path = patch_dir / name
            if not path.exists() or path.stat().st_size < 40:
                raise SystemExit(f"missing patch {path}")
        doc = ROOT / "organizer" / "docs" / service / "PATCH_MATRIX.md"
        text = doc.read_text()
        for required in ("Root cause", "Exploit steps", "Reference patch", "Checker coverage"):
            if required not in text:
                raise SystemExit(f"{doc} missing {required}")
    print("patch package ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
