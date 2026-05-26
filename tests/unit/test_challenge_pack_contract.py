from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import requests


ROOT = Path(__file__).resolve().parents[2]
CHALLENGES = ROOT / "platform" / "challenges"

SERVICES = {
    "svc1-ledgerforge": ("ledgerforge", "Cargo.toml", "rust-axum", 3, 5),
    "svc2-vaultgrid": ("vaultgrid", "Makefile", "cpp20-custom-http", 3, 5),
    "svc3-specterlog": ("specterlog", "package.json", "typescript-bun-fastify", 3, 5),
    "svc4-nanofleet": ("nanofleet", "go.mod", "go-net-http", 3, 5),
    "svc5-policyforge": ("policyforge", "mix.exs", "elixir-plug-cowboy", 3, 5),
}


def _run_feed_server(attack_info: str, service_slug: str, target: str, tick: int) -> tuple[ThreadingHTTPServer, str]:
    payloads = {
        "/api/teams.json": {"teams": [{"id": 1, "name": "testteam", "ip": target}]},
        "/api/attack.json": {
            "current_tick": tick,
            "flag_ids": {service_slug: {target: {str(tick): [attack_info]}}},
        },
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path not in payloads:
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps(payloads[self.path]).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


@pytest.mark.parametrize("directory,expected", SERVICES.items())
def test_service_pack_contract(directory: str, expected: tuple[str, str, str, int, int]) -> None:
    service_name, manifest, runtime, flagstores, vulnerabilities = expected
    base = CHALLENGES / directory
    files = [p for p in base.rglob("*") if p.is_file()]

    assert len(files) >= 20
    assert (base / "service" / manifest).exists()
    assert not (base / "service" / "app.py").exists()
    assert not (base / "service" / "requirements.txt").exists()

    meta = json.loads((base / "meta" / "service.json").read_text())
    assert meta["name"] == service_name
    assert meta["flagstores"] == flagstores
    assert meta["difficulty"] == "hard-100"
    assert meta["runtime"] == runtime
    assert meta["vulnerabilities"] == vulnerabilities
    assert meta["rabbit_holes"] == 5

    dockerfile = (base / "service" / "Dockerfile").read_text()
    assert "curl" in dockerfile
    assert "/docs" not in dockerfile
    assert "python:3.12-slim" not in dockerfile

    exploit_text = "\n".join(p.read_text(errors="ignore") for p in (base / "exploits").rglob("*.py"))
    assert "/attack-info" not in exploit_text
    assert "/attack-info" not in "\n".join(p.read_text(errors="ignore") for p in (base / "service").rglob("*") if p.is_file())


def test_compose_references_current_challenge_pack() -> None:
    for rel in ["docker-compose.yml", "infra/compose/team-stack.yml", "infra/compose/nop-stack.yml"]:
        text = (ROOT / rel).read_text()
        for path in [
            "svc1-ledgerforge/service/Dockerfile",
            "svc2-vaultgrid/service/Dockerfile",
            "svc3-specterlog/service/Dockerfile",
            "svc4-nanofleet/service/Dockerfile",
            "svc5-policyforge/service/Dockerfile",
        ]:
            assert path in text
        for old in ["svc1-heavensent", "svc2-pillarboxd", "svc3-gitter", "svc4-jitterish", "svc5-firewall"]:
            assert old not in text


def test_service_payload_defaults_are_two() -> None:
    init_db = (ROOT / "platform" / "control" / "app" / "init_db.py").read_text()
    for name in ["svc1", "svc2", "svc3", "svc4", "svc5", "ledgerforge", "vaultgrid", "specterlog", "nanofleet", "policyforge"]:
        assert f'"{name}": 2' in init_db


def test_scoreboard_uses_challenge_display_names_without_large_tick_panel() -> None:
    schema = (ROOT / "platform" / "control" / "app" / "schema.sql").read_text()
    init_db = (ROOT / "platform" / "control" / "app" / "init_db.py").read_text()
    main_py = (ROOT / "platform" / "control" / "app" / "main.py").read_text()
    scoreboard_api = (ROOT / "platform" / "control" / "app" / "scoreboard_api.py").read_text()
    scoreboard_ui = (ROOT / "platform" / "control" / "web" / "src" / "pages" / "Scoreboard.tsx").read_text()

    assert "display_name TEXT" in schema
    assert '"svc2": "VaultGrid"' in init_db
    assert "name AS slug" in main_py
    assert "COALESCE(NULLIF(display_name, ''), name) AS display_name" in main_py
    assert '"tick_activity": data.get("tick_activity")' in scoreboard_api
    assert "def _service_first_bloods" in main_py
    assert '"first_blood"] = first_blood' in main_py
    assert "first blood:" in scoreboard_ui
    assert "TickActivityPanel" not in scoreboard_ui
    assert "tick-activity" not in scoreboard_ui
    assert "serviceLabel(svc)" in scoreboard_ui


def test_putflag_attack_info_uses_compact_keys() -> None:
    banned = {"snapshot", "repair", "token", "archive", "blob", "policy"}
    checks = [
        CHALLENGES / "svc1-ledgerforge" / "service" / "src" / "state.rs",
        CHALLENGES / "svc2-vaultgrid" / "service" / "src" / "state.cpp",
        CHALLENGES / "svc3-specterlog" / "service" / "src" / "state.ts",
        CHALLENGES / "svc4-nanofleet" / "service" / "internal" / "state" / "state.go",
        CHALLENGES / "svc5-policyforge" / "service" / "lib" / "policy_forge" / "state.ex",
    ]
    for path in checks:
        text = path.read_text()
        compact_section = text[text.find("put_flag") if "put_flag" in text else text.find("PutFlag"):]
        for key in banned:
            assert f'"{key}"' not in compact_section


def test_team_challenge_export_is_sanitized(tmp_path: Path) -> None:
    out = tmp_path / "team-challenges"
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "export_team_challenges.py"), "--out", str(out)],
        check=True,
        cwd=ROOT,
    )
    for directory in SERVICES:
        service = out / directory
        assert (service / "service").is_dir()
        assert not (service / "checker").exists()
        assert not (service / "exploits").exists()
        assert not (service / "patches").exists()
        assert not (service / "README.md").exists()
        assert not any("docs" in p.parts for p in service.rglob("*"))
        assert sum(1 for p in (service / "service").rglob("*") if p.is_file()) >= 20
        lines = 0
        for path in (service / "service").rglob("*"):
            if path.is_file() and path.suffix in {".rs", ".cpp", ".hpp", ".ts", ".go", ".ex", ".exs", ".js", ".html", ".css"}:
                text = path.read_text(errors="ignore")
                lowered = text.lower()
                for term in ["vulnerability", "exploit", "solver", "rabbit", "decoy", "oracle", "flag leak", "private flag"]:
                    assert term not in lowered
                assert "//" not in text
                assert "/*" not in text
                assert "<!--" not in text
                assert not any(line.lstrip().startswith(("//", "/*", "<!--")) for line in text.splitlines())
                lines += len(text.splitlines())
        assert 3000 <= lines <= 10000


@pytest.mark.skipif(os.getenv("RUN_CHALLENGE_DOCKER_TESTS") != "1", reason="set RUN_CHALLENGE_DOCKER_TESTS=1 to build and run service images")
@pytest.mark.parametrize("directory,expected", SERVICES.items())
def test_docker_checker_and_solver_smoke(directory: str, expected: tuple[str, str, str, int, int]) -> None:
    service_name = expected[0]
    image = f"kossim-test-{service_name}"
    port = 28100 + list(SERVICES).index(directory)
    dockerfile = f"{directory}/service/Dockerfile"

    subprocess.run(
        ["docker", "build", "-t", image, "-f", dockerfile, "."],
        cwd=CHALLENGES,
        check=True,
    )
    cid = subprocess.check_output(
        [
            "docker",
            "run",
            "-d",
            "-p",
            f"{port}:8080",
            "-e",
            "SERVICE_PUSH_SECRET=rotate-secret",
            "-e",
            "TEAM_NAME=testteam",
            "-e",
            f"SERVICE_NAME={directory.split('-')[0]}",
            image,
        ],
        text=True,
    ).strip()
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(40):
            try:
                if requests.get(f"{base}/health", timeout=1).status_code == 200:
                    break
            except requests.RequestException:
                time.sleep(0.5)
        else:
            raise AssertionError("service did not become healthy")

        checker = CHALLENGES / directory / "checker" / "checker.py"
        solver = CHALLENGES / directory / "exploits" / "solver.py"
        subprocess.run([sys.executable, str(checker), base], check=True, env={**os.environ, "SERVICE_PUSH_SECRET": "rotate-secret"})
        out = subprocess.check_output([sys.executable, str(solver), base], text=True)
        assert "FLAG{" in out

        service_slug = directory.split("-")[0]
        tick = 7
        feed_flag = f"FLAG{{FEED_{service_name.upper()}_{tick}}}"
        put = requests.post(
            f"{base}/",
            headers={"X-Checker-Secret": "rotate-secret"},
            json={"method": "PUTFLAG", "current_round_id": tick, "variant_id": 0, "flag": feed_flag},
            timeout=5,
        )
        put.raise_for_status()
        assert put.json()["result"] == "OK"
        server, control = _run_feed_server(put.json()["attack_info"], service_slug, f"127.0.0.1:{port}", tick)
        try:
            feed_out = subprocess.check_output(
                [
                    sys.executable,
                    str(solver),
                    "--control",
                    control,
                    "--service",
                    service_slug,
                    "--target-ip",
                    f"127.0.0.1:{port}",
                    "--tick",
                    str(tick),
                ],
                text=True,
            )
        finally:
            server.shutdown()
            server.server_close()
        assert feed_flag in feed_out
    finally:
        subprocess.run(["docker", "rm", "-f", cid], check=False)
