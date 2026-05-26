from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHALLENGES = ROOT / "platform" / "challenges"


SERVICES = {
    "svc1": ("svc1-ledgerforge", "/var/lib/ledgerforge", 2, True),
    "svc2": ("svc2-vaultgrid", "/var/lib/vaultgrid", 2, True),
    "svc3": ("svc3-specterlog", "/var/lib/specterlog", 3, False),
    "svc4": ("svc4-nanofleet", "/var/lib/nanofleet", 2, True),
    "svc5": ("svc5-policyforge", "/var/lib/policyforge", 2, True),
}


def test_service_metadata_and_checker_capabilities() -> None:
    common = (CHALLENGES / "common" / "ecsc_checker.py").read_text()
    for svc, (directory, _, flagstores, uses_common_checker) in SERVICES.items():
        base = CHALLENGES / directory
        meta = json.loads((base / "meta" / "service.json").read_text())
        assert meta["flagstores"] == flagstores
        assert meta["vulnerabilities"] >= 2
        checker = (base / "checker" / "checker.py").read_text()
        if uses_common_checker:
            assert "common.ecsc_checker" in checker
        else:
            assert "enochecker3" in (base / "checker" / "src" / "checker.py").read_text()
        for method in ("PUTFLAG", "GETFLAG", "PUTNOISE", "GETNOISE", "HAVOC"):
            assert method in common
        assert (ROOT / "organizer" / "exploits" / svc / "exploit_fs0.py").exists()
        assert (ROOT / "organizer" / "exploits" / svc / "exploit_fs1.py").exists()


def test_persistence_paths_are_declared() -> None:
    compose = (ROOT / "docker-compose.yml").read_text()
    for _, data_path, _, _ in SERVICES.values():
        assert data_path in compose
    for directory, data_path, _, _ in SERVICES.values():
        dockerfile = (CHALLENGES / directory / "service" / "Dockerfile").read_text()
        assert data_path in dockerfile


def test_organizer_patch_package_complete() -> None:
    for svc in SERVICES:
        patch_dir = ROOT / "organizer" / "patches" / svc
        for name in ("vuln0.patch", "vuln1.patch", "all.patch"):
            text = (patch_dir / name).read_text()
            assert text.startswith("diff --git")
        doc = (ROOT / "organizer" / "docs" / svc / "PATCH_MATRIX.md").read_text()
        for term in ("Root cause", "Exploit steps", "Reference patch", "Checker coverage", "Persistence notes"):
            assert term in doc


def test_unique_interaction_markers_present() -> None:
    assert "/api/v1/commit" in (CHALLENGES / "svc1-ledgerforge" / "service" / "src" / "routes.rs").read_text()
    assert "run_repair_server" in (CHALLENGES / "svc2-vaultgrid" / "service" / "src" / "main.cpp").read_text()
    assert '"/ws"' in (CHALLENGES / "svc3-specterlog" / "service" / "src" / "routes.ts").read_text()
    assert "/api/v2/jobs" in (CHALLENGES / "svc4-nanofleet" / "service" / "internal" / "routes" / "routes.go").read_text()
    assert 'post "/rpc"' in (CHALLENGES / "svc5-policyforge" / "service" / "lib" / "policy_forge" / "router.ex").read_text()
