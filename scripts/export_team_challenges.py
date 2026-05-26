#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHALLENGES = ROOT / "platform" / "challenges"
DEFAULT_OUT = ROOT / "dist" / "team-challenges"

SERVICE_GLOB = "svc*-*"
SOURCE_SUFFIXES = {
    ".rs", ".cpp", ".hpp", ".ts", ".go", ".ex", ".exs", ".js", ".html",
    ".css", ".toml", ".json", ".proto", ".lf", ".mod",
}
SOURCE_NAMES = {"Dockerfile", "Makefile"}
SKIP_PARTS = {
    "checker", "exploits", "patches", "meta", "docs", "__pycache__",
    "node_modules", "target", "_build", "deps",
}
SKIP_FILE_NAMES = {"README.md", "decoys.json"}
SKIP_SUFFIXES = {".map", ".pyc"}
RENAME_PARTS = {
    "rabbits": "ops",
    "rabbit": "ops",
    "oracle": "preview",
    "decoy": "sample",
}
TEXT_REPLACEMENTS = {
    "rabbits": "ops",
    "rabbit": "ops",
    "Rabbit": "Ops",
    "decoy": "sample",
    "Decoy": "Sample",
    "oracle": "preview",
    "Oracle": "Preview",
    "vulnerability": "condition",
    "Vulnerability": "Condition",
    "exploit": "client",
    "Exploit": "Client",
    "solver": "client",
    "Solver": "Client",
    "flag leak": "data exposure",
    "private flag": "restricted record",
}
FORBIDDEN_TERMS = [
    "vulnerability",
    "exploit",
    "solver",
    "rabbit",
    "decoy",
    "oracle",
    "flag leak",
    "private flag",
]
PUBLIC_LINE_EXTS = {".rs", ".cpp", ".hpp", ".ts", ".go", ".ex", ".exs", ".js", ".html", ".css"}


def is_text_file(path: Path) -> bool:
    return path.name in SOURCE_NAMES or path.suffix in SOURCE_SUFFIXES


def should_skip(path: Path, service_root: Path) -> bool:
    rel = path.relative_to(service_root)
    if any(part in SKIP_PARTS for part in rel.parts):
        return True
    if path.name in SKIP_FILE_NAMES:
        return True
    if path.suffix in SKIP_SUFFIXES:
        return True
    if "decoy" in path.name.lower():
        return True
    return False


def rename_part(part: str) -> str:
    out = part
    for src, dst in RENAME_PARTS.items():
        out = re.sub(src, dst, out, flags=re.IGNORECASE)
    return out


def export_path(src: Path, service_root: Path, dest_service_root: Path) -> Path:
    rel = src.relative_to(service_root)
    parts = [rename_part(part) for part in rel.parts]
    return dest_service_root.joinpath(*parts)


def strip_comments(text: str, suffix: str, name: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("//"):
            continue
        if suffix in {".ex", ".exs"} and stripped.startswith("#"):
            continue
        if name == "Dockerfile" and stripped.startswith("#"):
            continue
        out.append(line.rstrip())
    return "\n".join(out).strip() + "\n"


def sanitize_text(text: str, suffix: str, name: str) -> str:
    text = strip_comments(text, suffix, name)
    for src, dst in TEXT_REPLACEMENTS.items():
        text = text.replace(src, dst)
    return text


def copy_service(service_dir: Path, out_root: Path) -> None:
    dest_service = out_root / service_dir.name
    src_service = service_dir / "service"
    for src in src_service.rglob("*"):
        if src.is_dir() or should_skip(src, service_dir):
            continue
        dest = export_path(src, service_dir, dest_service)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if is_text_file(src):
            text = src.read_text(errors="ignore")
            dest.write_text(sanitize_text(text, src.suffix, src.name))
        else:
            shutil.copy2(src, dest)


def validate_export(out_root: Path) -> None:
    failures: list[str] = []
    for service in sorted(out_root.glob(SERVICE_GLOB)):
        line_count = 0
        file_count = 0
        for path in service.rglob("*"):
            if path.is_dir():
                continue
            file_count += 1
            lower_path = "/".join(part.lower() for part in path.relative_to(service).parts)
            if any(part in lower_path.split("/") for part in SKIP_PARTS):
                failures.append(f"excluded path present: {path}")
            if path.name in SKIP_FILE_NAMES or path.suffix in SKIP_SUFFIXES:
                failures.append(f"excluded file present: {path}")
            if is_text_file(path):
                text = path.read_text(errors="ignore")
                low = text.lower()
                for term in FORBIDDEN_TERMS:
                    if term in low:
                        failures.append(f"forbidden term {term!r}: {path}")
                for marker in ("//", "<!--"):
                    if marker in text:
                        failures.append(f"comment marker {marker!r}: {path}")
                        break
                for idx, line in enumerate(text.splitlines(), start=1):
                    stripped = line.lstrip()
                    if stripped.startswith(("//", "/*", "<!--")):
                        failures.append(f"comment-like line {idx}: {path}")
                        break
                if path.suffix in PUBLIC_LINE_EXTS:
                    line_count += len(text.splitlines())
        if not (3000 <= line_count <= 10000):
            failures.append(f"{service.name} has {line_count} public source lines, expected 3000-10000")
        if file_count < 20:
            failures.append(f"{service.name} has {file_count} public files, expected at least 20")
    if failures:
        raise SystemExit("\n".join(failures))


def export(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for service_dir in sorted(CHALLENGES.glob(SERVICE_GLOB)):
        if service_dir.is_dir():
            copy_service(service_dir, out)
    validate_export(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build sanitized team challenge source package.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    export(args.out)
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
