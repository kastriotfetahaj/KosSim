#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CHALLENGES = ROOT / "platform" / "challenges"

SERVICE_DATA_PATHS = {
    "svc1-ledgerforge": "/var/lib/ledgerforge",
    "svc2-vaultgrid": "/var/lib/vaultgrid",
    "svc3-specterlog": "/var/lib/specterlog",
    "svc4-nanofleet": "/var/lib/nanofleet",
    "svc5-policyforge": "/var/lib/policyforge",
}


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def load_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        fail(errors, f"{path}: invalid JSON: {exc}")
        return {}


def count_exp_scripts(path: Path) -> int:
    return sum(1 for p in path.glob("exp*.py") if p.is_file())


def patch_files(path: Path) -> list[Path]:
    return sorted(p for p in path.rglob("*.patch") if p.is_file())


def assert_init_payload(init_db: str, name: str, slot: str, flagstores: int, errors: list[str]) -> None:
    for key in (slot, name):
        if not re.search(rf'"{re.escape(key)}"\s*:\s*{flagstores}\b', init_db):
            fail(errors, f"init_db.py payload count for {key} does not match flagstores={flagstores}")


def validate_service(service_dir: Path, init_db: str, root_compose: str, infra_compose: str, errors: list[str]) -> None:
    meta_path = service_dir / "meta" / "service.json"
    meta = load_json(meta_path, errors)
    if not meta:
        return

    required = [
        "name",
        "slot",
        "categories",
        "flagstores",
        "noisestores",
        "havoc_variants",
        "difficulty",
        "runtime",
        "persistence",
        "vulnerabilities",
        "rabbit_holes",
        "exploit_scripts",
        "checker",
    ]
    for key in required:
        if key not in meta:
            fail(errors, f"{service_dir.name}: missing metadata key {key}")

    slot = str(meta.get("slot", ""))
    name = str(meta.get("name", ""))
    flagstores = int(meta.get("flagstores") or 0)
    vulnerabilities = int(meta.get("vulnerabilities") or 0)
    declared_exploits = int(meta.get("exploit_scripts") or 0)

    if not service_dir.name.startswith(f"{slot}-"):
        fail(errors, f"{service_dir.name}: slot {slot!r} does not match directory")
    if flagstores < 1:
        fail(errors, f"{service_dir.name}: flagstores must be positive")
    if int(meta.get("noisestores") or 0) < 1:
        fail(errors, f"{service_dir.name}: noisestores must be positive")
    if int(meta.get("havoc_variants") or 0) < 3:
        fail(errors, f"{service_dir.name}: havoc_variants should be at least 3")
    if int(meta.get("rabbit_holes") or 0) < 3:
        fail(errors, f"{service_dir.name}: rabbit_holes should be at least 3")
    if meta.get("difficulty") != "hard-100":
        fail(errors, f"{service_dir.name}: difficulty should be hard-100")

    assert_init_payload(init_db, name, slot, flagstores, errors)

    dockerfile = service_dir / "service" / "Dockerfile"
    if not dockerfile.exists():
        fail(errors, f"{service_dir.name}: missing service Dockerfile")
    else:
        docker_text = dockerfile.read_text()
        if "curl" not in docker_text:
            fail(errors, f"{service_dir.name}: Dockerfile should include curl for healthchecks")
        data_path = SERVICE_DATA_PATHS.get(service_dir.name)
        if data_path and data_path not in docker_text:
            fail(errors, f"{service_dir.name}: Dockerfile missing persistence path {data_path}")

    dockerfile_ref = f"{service_dir.name}/service/Dockerfile"
    if dockerfile_ref not in root_compose:
        fail(errors, f"docker-compose.yml missing {dockerfile_ref}")
    if dockerfile_ref not in infra_compose:
        fail(errors, f"infra compose files missing {dockerfile_ref}")
    data_path = SERVICE_DATA_PATHS.get(service_dir.name)
    if data_path and data_path not in root_compose:
        fail(errors, f"docker-compose.yml missing persistence path {data_path}")

    checker = service_dir / "checker" / "checker.py"
    if not checker.exists():
        fail(errors, f"{service_dir.name}: missing sync checker")
    else:
        checker_text = checker.read_text(errors="ignore")
        for method in ("PUTFLAG", "GETFLAG", "PUTNOISE", "GETNOISE", "HAVOC"):
            if method not in checker_text:
                fail(errors, f"{service_dir.name}: sync checker missing {method}")
        if "attack_info" not in checker_text:
            fail(errors, f"{service_dir.name}: checker does not validate attack_info")

    checker_meta = meta.get("checker") or {}
    async_app = checker_meta.get("async_app")
    if async_app:
        async_path = service_dir / str(async_app)
        if not async_path.exists():
            fail(errors, f"{service_dir.name}: declared async checker missing at {async_app}")

    actual_exploits = count_exp_scripts(service_dir / "exploits")
    if actual_exploits != declared_exploits:
        fail(errors, f"{service_dir.name}: exploit_scripts={declared_exploits}, found {actual_exploits}")
    if not (service_dir / "exploits" / "solver.py").exists():
        fail(errors, f"{service_dir.name}: missing solver.py")

    patches = patch_files(service_dir / "patches")
    if len(patches) != vulnerabilities:
        fail(errors, f"{service_dir.name}: vulnerabilities={vulnerabilities}, patches={len(patches)}")

    workflow = service_dir / ".github" / "workflows" / "ci.yml"
    if not workflow.exists():
        fail(errors, f"{service_dir.name}: missing per-service CI workflow")


def validate() -> list[str]:
    errors: list[str] = []
    init_db = (ROOT / "platform" / "control" / "app" / "init_db.py").read_text()
    root_compose = (ROOT / "docker-compose.yml").read_text()
    infra_compose = "\n".join(
        p.read_text() for p in sorted((ROOT / "infra" / "compose").glob("*.yml"))
    )

    service_dirs = sorted(p for p in CHALLENGES.glob("svc*-*") if p.is_dir())
    if len(service_dirs) != 5:
        fail(errors, f"expected 5 service packs, found {len(service_dirs)}")
    for service_dir in service_dirs:
        validate_service(service_dir, init_db, root_compose, infra_compose, errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate KosSim platform/challenge consistency.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable result")
    args = parser.parse_args()

    errors = validate()
    if args.json:
        print(json.dumps({"ok": not errors, "errors": errors}, indent=2))
    elif errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
    else:
        print("platform validation OK")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
