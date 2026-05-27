#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import List


REQ_SERVICE_SECRET = "${SERVICE_PUSH_SECRET:?set SERVICE_PUSH_SECRET}"
REQ_FLAG_SECRET = "${SECRET_FLAG_KEY:?set SECRET_FLAG_KEY}"
REQ_ADMIN_PASSWORD = "${ADMIN_PASSWORD:?set ADMIN_PASSWORD}"
REQ_ADMIN_SESSION = "${ADMIN_SESSION_SECRET:?set ADMIN_SESSION_SECRET}"
REQ_GAME_TOKEN = "${GAME_ADMIN_TOKEN:?set GAME_ADMIN_TOKEN}"
REQ_POSTGRES_PASSWORD = "${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD}"


def _parse_team_names(raw: str) -> List[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _team_names(args: argparse.Namespace) -> List[str]:
    if args.teams:
        names = _parse_team_names(args.teams)
        if names:
            return names
    return [f"team{i}" for i in range(1, args.team_count + 1)]


def _curl_healthcheck(port: int = 8080, indent: int = 2) -> str:
    pad = " " * indent
    child = " " * (indent + 2)
    return f"""{pad}healthcheck:
{child}test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:{port}/health >/dev/null"]
{child}interval: 10s
{child}timeout: 3s
{child}retries: 6
{child}start_period: 10s
"""


def _svc_anchor(num: int, dockerfile: str) -> str:
    return f"""x-svc{num}: &svc{num}
  build:
    context: ./platform/challenges
    dockerfile: {dockerfile}
  restart: unless-stopped
  environment:
    SERVICE_PUSH_SECRET: {REQ_SERVICE_SECRET}
  mem_limit: 384m
  cpus: 0.75
{_curl_healthcheck(8080, 2)}  networks:
    - ctf_net
"""


SVCS_WITH_NAMED_VOLUME = {
    1: ("ledgerforge_{team}_data", "/var/lib/ledgerforge"),
    2: ("vaultgrid_{team}_data", "/var/lib/vaultgrid"),
    3: ("specterlog_{team}_data", "/var/lib/specterlog"),
    4: ("nanofleet_{team}_data", "/var/lib/nanofleet"),
    5: ("policyforge_{team}_data", "/var/lib/policyforge"),
}


def _service_volume_block(svc_num: int, team: str) -> str:
    if svc_num not in SVCS_WITH_NAMED_VOLUME:
        return ""
    vol_template, mount = SVCS_WITH_NAMED_VOLUME[svc_num]
    vol = vol_template.format(team=team)
    return f"    volumes:\n      - {vol}:{mount}\n"


def _svc2_sidecars(team: str) -> str:
    crypt_vol = f"vaultgrid_crypt_{team}_data"
    feed_vol = f"vaultgrid_feed_{team}_data"
    return f"""  {team}-vg-crypt:
    build:
      context: ./platform/challenges
      dockerfile: svc2-vaultgrid/crypt/Dockerfile
    restart: unless-stopped
    environment:
      SERVICE_PUSH_SECRET: {REQ_SERVICE_SECRET}
    volumes:
      - {crypt_vol}:/var/lib/vaultgrid-crypt
    mem_limit: 192m
    cpus: 0.4
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:4102/health >/dev/null"]
      interval: 10s
      timeout: 3s
      retries: 6
      start_period: 10s
    networks:
      - ctf_net

  {team}-vg-feed:
    build:
      context: ./platform/challenges
      dockerfile: svc2-vaultgrid/feed/Dockerfile
    restart: unless-stopped
    environment:
      SERVICE_PUSH_SECRET: {REQ_SERVICE_SECRET}
    volumes:
      - {feed_vol}:/var/lib/vaultgrid-feed
    mem_limit: 192m
    cpus: 0.4
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:4103/health >/dev/null"]
      interval: 10s
      timeout: 3s
      retries: 6
      start_period: 10s
    networks:
      - ctf_net

"""


def _team_service_block(team: str, svc_num: int) -> str:
    extras = ""
    if svc_num == 2:
        extras = (
            f"      VAULTGRID_CRYPT_HOST: {team}-vg-crypt\n"
            f"      VAULTGRID_CRYPT_PORT: 4102\n"
            f"      VAULTGRID_FEED_HOST: {team}-vg-feed\n"
            f"      VAULTGRID_FEED_PORT: 4103\n"
        )
    block = f"""  {team}-svc{svc_num}:
    <<: *svc{svc_num}
    environment:
      TEAM_NAME: {team}
      SERVICE_NAME: svc{svc_num}
      BOOT_FLAG: FLAG{{BOOT_{team}_svc{svc_num}}}
      SERVICE_PUSH_SECRET: {REQ_SERVICE_SECRET}
{extras}{_service_volume_block(svc_num, team)}"""
    if svc_num == 2:
        block += _svc2_sidecars(team)
    return block


def _nop_service_block(svc_num: int) -> str:
    return f"""  nop-svc{svc_num}:
    <<: *svc{svc_num}
    environment:
      TEAM_NAME: nop
      SERVICE_NAME: svc{svc_num}
      BOOT_FLAG: FLAG{{NOP_svc{svc_num}}}
      SERVICE_PUSH_SECRET: {REQ_SERVICE_SECRET}
{_service_volume_block(svc_num, "nop")}"""


def _render_compose(teams: List[str], include_nop: bool) -> str:
    teams_csv = ",".join(teams)
    svc_dockerfiles = {
        1: "svc1-ledgerforge/service/Dockerfile",
        2: "svc2-vaultgrid/service/Dockerfile",
        3: "svc3-specterlog/service/Dockerfile",
        4: "svc4-nanofleet/service/Dockerfile",
        5: "svc5-policyforge/service/Dockerfile",
    }

    parts: List[str] = []
    parts.append(
        f"""name: kossim

x-control-env: &control-env
  DATABASE_URL: postgresql://kossim:{REQ_POSTGRES_PASSWORD}@postgres:5432/kossim
  TEAMS: {teams_csv}
  TEAM_COUNTRIES: ${{TEAM_COUNTRIES:-}}
  DEFAULT_COUNTRY_CODE: ${{DEFAULT_COUNTRY_CODE:-XK}}
  SERVICE_NAMES: svc1,svc2,svc3,svc4,svc5
  NOP_TEAM_NAME: nop
  TEAM_TOKEN_PREFIX: ${{TEAM_TOKEN_PREFIX:-submit-}}
  SUBMISSION_POINTS: ${{SUBMISSION_POINTS:-1}}
  MAX_ACCEPTED_PER_TEAM_PER_ROUND: ${{MAX_ACCEPTED_PER_TEAM_PER_ROUND:-0}}
  ROTATION_SECONDS: ${{ROTATION_SECONDS:-120}}
  FLAG_RETENTION_TICKS: ${{FLAG_RETENTION_TICKS:-5}}
  GAME_AUTO_START: ${{GAME_AUTO_START:-1}}
  FLAG_TCP_ENABLED: ${{FLAG_TCP_ENABLED:-1}}
  FLAG_TCP_PORT: ${{FLAG_TCP_PORT:-1337}}
  SCOREBOARD_FREEZE_TICK: ${{SCOREBOARD_FREEZE_TICK:-0}}
  SERVICE_PUSH_SECRET: {REQ_SERVICE_SECRET}
  SECRET_FLAG_KEY: {REQ_FLAG_SECRET}
  ADMIN_USERNAME: ${{ADMIN_USERNAME:-admin}}
  ADMIN_PASSWORD: {REQ_ADMIN_PASSWORD}
  ADMIN_SESSION_SECRET: {REQ_ADMIN_SESSION}
  GAME_ADMIN_TOKEN: {REQ_GAME_TOKEN}
  CHECKER_CONCURRENCY: ${{CHECKER_CONCURRENCY:-8}}
  CHECKER_MAX_ATTEMPTS: ${{CHECKER_MAX_ATTEMPTS:-2}}
  CHECKER_RETRY_DELAY_SECONDS: ${{CHECKER_RETRY_DELAY_SECONDS:-3}}
  SERVICE_HTTP_TIMEOUT: ${{SERVICE_HTTP_TIMEOUT:-3.0}}
  SERVICE_CHECK_BUDGET_SECONDS: ${{SERVICE_CHECK_BUDGET_SECONDS:-25}}
  REDIS_URL: redis://redis:6379/0
  CELERY_BROKER_URL: redis://redis:6379/0
  CELERY_RESULT_BACKEND: redis://redis:6379/0
  VULNBOX_COMPOSE_BIN: ${{VULNBOX_COMPOSE_BIN:-docker compose}}
  VULNBOX_COMPOSE_FILE: ${{VULNBOX_COMPOSE_FILE:-/workspace/docker-compose.yml}}
  VULNBOX_COMPOSE_PROJECT: ${{VULNBOX_COMPOSE_PROJECT:-kossim}}
  AUTOINIT_DB: "1"
"""
    )

    for svc_num in range(1, 6):
        parts.append(_svc_anchor(svc_num, svc_dockerfiles[svc_num]))

    parts.append(
        f"""services:
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: kossim
      POSTGRES_USER: kossim
      POSTGRES_PASSWORD: {REQ_POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U kossim -d kossim"]
      interval: 10s
      timeout: 3s
      retries: 10
      start_period: 10s
    mem_limit: 512m
    cpus: 1.0
    networks:
      - ctf_net

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: ["redis-server", "--appendonly", "yes"]
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 10
      start_period: 5s
    mem_limit: 256m
    cpus: 0.5
    networks:
      - ctf_net

  control-api:
    build:
      context: ./platform/control
    restart: unless-stopped
    environment: *control-env
    volumes:
      - ./platform/challenges:/challenges:ro
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    ports:
      - "8088:8000"
      - "1337:1337"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()"]
      interval: 10s
      timeout: 3s
      retries: 12
      start_period: 20s
    mem_limit: 512m
    cpus: 1.0
    networks:
      - ctf_net

  flag-rotator:
    build:
      context: ./platform/control
    restart: unless-stopped
    environment: *control-env
    command: ["python", "-m", "app.rotator"]
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      control-api:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import os, psycopg2; conn = psycopg2.connect(os.environ['DATABASE_URL']); conn.close()"]
      interval: 15s
      timeout: 5s
      retries: 6
      start_period: 20s
    mem_limit: 512m
    cpus: 1.0
    networks:
      - ctf_net

  checker-worker:
    build:
      context: ./platform/control
    restart: unless-stopped
    user: "0:0"
    environment: *control-env
    volumes:
      - ./platform/challenges:/challenges:ro
      - /var/run/docker.sock:/var/run/docker.sock
      - .:/workspace:ro
    command: ["sh", "-c", "celery -A app.worker:celery_app worker --loglevel=${{CELERY_LOG_LEVEL:-INFO}} --concurrency=${{CHECKER_WORKER_CONCURRENCY:-4}} -Q checkers,vulnboxes,celery"]
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import os, redis; redis.Redis.from_url(os.environ['REDIS_URL']).ping()"]
      interval: 15s
      timeout: 5s
      retries: 6
      start_period: 20s
    mem_limit: 768m
    cpus: 1.0
    networks:
      - ctf_net
"""
    )

    for team in teams:
        for svc_num in range(1, 6):
            parts.append(_team_service_block(team, svc_num))

    if include_nop:
        for svc_num in range(1, 6):
            parts.append(_nop_service_block(svc_num))

    named_volume_lines = ["volumes:", "  postgres_data:", "  redis_data:"]
    for svc_num, (vol_template, _mount) in SVCS_WITH_NAMED_VOLUME.items():
        for team in teams:
            named_volume_lines.append(f"  {vol_template.format(team=team)}:")
        if include_nop:
            named_volume_lines.append(f"  {vol_template.format(team='nop')}:")
    target_teams = list(teams) + (["nop"] if include_nop else [])
    for team in target_teams:
        named_volume_lines.append(f"  vaultgrid_crypt_{team}_data:")
        named_volume_lines.append(f"  vaultgrid_feed_{team}_data:")
    named_volume_block = "\n".join(named_volume_lines) + "\n"

    parts.append(
        named_volume_block
        + """
networks:
  ctf_net:
    driver: bridge
"""
    )

    return "\n".join(parts).strip() + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a local docker compose file with 5 challenge services per team."
    )
    parser.add_argument(
        "--team-count",
        type=int,
        default=2,
        help="How many team stacks to generate when --teams is not set.",
    )
    parser.add_argument(
        "--teams",
        default="",
        help="Explicit team names as CSV (example: team1,team2,team3).",
    )
    parser.add_argument(
        "--without-nop",
        action="store_true",
        help="Do not include nop service stack.",
    )
    parser.add_argument(
        "--output",
        default="docker-compose.generated.yml",
        help="Output compose file path.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()

    if args.team_count < 1:
        raise SystemExit("--team-count must be >= 1")

    teams = _team_names(args)
    if not teams:
        raise SystemExit("No teams resolved from --team-count/--teams")

    output_path = Path(args.output)
    content = _render_compose(teams, not args.without_nop)
    output_path.write_text(content, encoding="utf-8")

    print(f"Generated {output_path} for teams: {', '.join(teams)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
