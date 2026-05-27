from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List

from .db import get_cursor


def _parse_csv(raw: str) -> List[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _parse_map(raw: str) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for pair in _parse_csv(raw):
        if "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            mapping[key] = value
    return mapping


def _load_schema() -> str:
    schema_path = Path(__file__).with_name("schema.sql")
    return schema_path.read_text()


def _get_services() -> List[str]:
    return _parse_csv(os.getenv("SERVICE_NAMES", "svc1,svc2,svc3,svc4,svc5"))


# Per-service flagstore count, mirroring `services.sql` from the ECSC
# gameserver. Falls back to 1 when the service is not in this table.
_SERVICE_PAYLOADS: Dict[str, int] = {
    "svc1": 3,
    "svc2": 3,
    "svc3": 3,
    "svc4": 3,
    "svc5": 3,
    # Friendly aliases for the advanced KosSim service packages.
    "ledgerforge": 3,
    "vaultgrid": 3,
    "specterlog": 3,
    "nanofleet": 3,
    "policyforge": 3,
}

_DEFAULT_SERVICE_DISPLAY_NAMES: Dict[str, str] = {
    "svc1": "LedgerForge",
    "svc2": "VaultGrid",
    "svc3": "SpecterLog",
    "svc4": "NanoFleet",
    "svc5": "PolicyForge",
    "ledgerforge": "LedgerForge",
    "vaultgrid": "VaultGrid",
    "specterlog": "SpecterLog",
    "nanofleet": "NanoFleet",
    "policyforge": "PolicyForge",
}


def _payloads_for(service_name: str) -> int:
    return _SERVICE_PAYLOADS.get(service_name, 1)


def _display_name_for(service_name: str) -> str:
    overrides = _parse_map(os.getenv("SERVICE_DISPLAY_NAMES", ""))
    return overrides.get(service_name, _DEFAULT_SERVICE_DISPLAY_NAMES.get(service_name, service_name))


def _get_team_names() -> List[str]:
    teams = _parse_csv(os.getenv("TEAMS", "team1,team2"))
    return teams or ["team1", "team2"]


def _host_for_team_service(team: str, service_name: str, nop_name: str, service_index: int) -> tuple[str, int]:
    team_host_map = _parse_map(os.getenv("TEAM_HOST_MAP", ""))
    service_port_map_raw = _parse_map(os.getenv("SERVICE_PORT_MAP", ""))
    service_port_map = {name: int(port) for name, port in service_port_map_raw.items() if port.isdigit()}

    default_remote_port = int(os.getenv("DEFAULT_REMOTE_SERVICE_PORT", "22001"))

    if team in team_host_map:
        host = team_host_map[team]
        port = service_port_map.get(service_name, default_remote_port + service_index)
        return host, port

    nop_host = os.getenv("NOP_HOST", "")
    if team == nop_name and nop_host:
        host = nop_host
        port = service_port_map.get(service_name, default_remote_port + service_index)
        return host, port

    return f"{team}-{service_name}", 8080


def bootstrap_database() -> None:
    schema_sql = _load_schema()
    teams = _get_team_names()
    services = _get_services()
    nop_name = os.getenv("NOP_TEAM_NAME", "nop")
    token_prefix = os.getenv("TEAM_TOKEN_PREFIX", "submit-")

    all_teams = teams + [nop_name]

    team_countries = _parse_map(os.getenv("TEAM_COUNTRIES", ""))
    default_country = os.getenv("DEFAULT_COUNTRY_CODE", "XK")

    with get_cursor(commit=True) as (_conn, cur):
        cur.execute(schema_sql)
        cur.execute("ALTER TABLE submissions ADD COLUMN IF NOT EXISTS round_id BIGINT;")
        cur.execute("ALTER TABLE submissions ADD COLUMN IF NOT EXISTS tick_issued INTEGER;")
        cur.execute("ALTER TABLE submissions ADD COLUMN IF NOT EXISTS payload INTEGER;")
        cur.execute(
            "ALTER TABLE submissions ADD COLUMN IF NOT EXISTS is_firstblood BOOLEAN NOT NULL DEFAULT FALSE;"
        )
        cur.execute(
            f"ALTER TABLE teams ADD COLUMN IF NOT EXISTS country_code TEXT NOT NULL DEFAULT '{default_country}';"
        )
        cur.execute("ALTER TABLE flag_rounds ADD COLUMN IF NOT EXISTS tick INTEGER;")
        cur.execute(
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'flag_rounds_tick_key') THEN "
            "ALTER TABLE flag_rounds ADD CONSTRAINT flag_rounds_tick_key UNIQUE (tick); "
            "END IF; END $$;"
        )
        cur.execute("ALTER TABLE flags ADD COLUMN IF NOT EXISTS payload INTEGER NOT NULL DEFAULT 0;")
        cur.execute("ALTER TABLE flags ADD COLUMN IF NOT EXISTS attack_info TEXT;")
        cur.execute(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'flags_team_id_service_id_round_id_key') THEN "
            "ALTER TABLE flags DROP CONSTRAINT flags_team_id_service_id_round_id_key; "
            "END IF; END $$;"
        )
        cur.execute(
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'flags_unique_full') THEN "
            "ALTER TABLE flags ADD CONSTRAINT flags_unique_full UNIQUE (team_id, service_id, round_id, payload); "
            "END IF; END $$;"
        )
        cur.execute(
            "ALTER TABLE services ADD COLUMN IF NOT EXISTS num_payloads INTEGER NOT NULL DEFAULT 1;"
        )
        cur.execute(
            "ALTER TABLE services ADD COLUMN IF NOT EXISTS flags_per_tick INTEGER NOT NULL DEFAULT 1;"
        )
        cur.execute("ALTER TABLE services ADD COLUMN IF NOT EXISTS display_name TEXT;")
        cur.execute("ALTER TABLE service_health ADD COLUMN IF NOT EXISTS tick INTEGER;")
        cur.execute(
            "ALTER TABLE service_health ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'OFFLINE';"
        )
        cur.execute("ALTER TABLE service_health ADD COLUMN IF NOT EXISTS message TEXT;")
        cur.execute("ALTER TABLE service_health ADD COLUMN IF NOT EXISTS attack_info TEXT;")
        cur.execute(
            "ALTER TABLE service_health ADD COLUMN IF NOT EXISTS flag_avail JSONB NOT NULL DEFAULT '{}'::jsonb;"
        )
        cur.execute(
            "ALTER TABLE service_health ADD COLUMN IF NOT EXISTS runtime_seconds NUMERIC(10, 3);"
        )
        # Component scoring uses fractional point values; migrate any older
        # INTEGER columns up to NUMERIC and add new score components in place.
        cur.execute("ALTER TABLE scores ADD COLUMN IF NOT EXISTS uptime_points NUMERIC(14, 4) NOT NULL DEFAULT 0;")
        cur.execute(
            "ALTER TABLE scores ADD COLUMN IF NOT EXISTS hacked_penalty_points NUMERIC(14, 4) NOT NULL DEFAULT 0;"
        )
        cur.execute("ALTER TABLE scores ADD COLUMN IF NOT EXISTS challenge_points NUMERIC(14, 4) NOT NULL DEFAULT 0;")
        cur.execute("ALTER TABLE scores ALTER COLUMN attack_points TYPE NUMERIC(14, 4) USING attack_points::numeric;")
        cur.execute("ALTER TABLE scores ALTER COLUMN defense_points TYPE NUMERIC(14, 4) USING defense_points::numeric;")
        cur.execute("ALTER TABLE scores ALTER COLUMN uptime_points TYPE NUMERIC(14, 4) USING uptime_points::numeric;")
        cur.execute(
            "ALTER TABLE scores ALTER COLUMN hacked_penalty_points TYPE NUMERIC(14, 4) "
            "USING hacked_penalty_points::numeric;"
        )
        cur.execute("ALTER TABLE scores ALTER COLUMN challenge_points TYPE NUMERIC(14, 4) USING challenge_points::numeric;")
        cur.execute("ALTER TABLE scores ALTER COLUMN sla_points TYPE NUMERIC(14, 4) USING sla_points::numeric;")
        cur.execute("ALTER TABLE scores ALTER COLUMN total TYPE NUMERIC(14, 4) USING total::numeric;")
        cur.execute("ALTER TABLE score_snapshots ADD COLUMN IF NOT EXISTS defense_points NUMERIC(14, 4) NOT NULL DEFAULT 0;")
        cur.execute("ALTER TABLE score_snapshots ADD COLUMN IF NOT EXISTS uptime_points NUMERIC(14, 4) NOT NULL DEFAULT 0;")
        cur.execute(
            "ALTER TABLE score_snapshots ADD COLUMN IF NOT EXISTS hacked_penalty_points NUMERIC(14, 4) "
            "NOT NULL DEFAULT 0;"
        )
        cur.execute(
            "ALTER TABLE score_snapshots ADD COLUMN IF NOT EXISTS challenge_points NUMERIC(14, 4) NOT NULL DEFAULT 0;"
        )
        cur.execute("ALTER TABLE score_snapshots ADD COLUMN IF NOT EXISTS service_total NUMERIC(14, 4) NOT NULL DEFAULT 0;")
        cur.execute(
            "ALTER TABLE score_snapshots ALTER COLUMN attack_points TYPE NUMERIC(14, 4) USING attack_points::numeric;"
        )
        cur.execute(
            "ALTER TABLE score_snapshots ALTER COLUMN defense_points TYPE NUMERIC(14, 4) USING defense_points::numeric;"
        )
        cur.execute(
            "ALTER TABLE score_snapshots ALTER COLUMN uptime_points TYPE NUMERIC(14, 4) USING uptime_points::numeric;"
        )
        cur.execute(
            "ALTER TABLE score_snapshots ALTER COLUMN hacked_penalty_points TYPE NUMERIC(14, 4) "
            "USING hacked_penalty_points::numeric;"
        )
        cur.execute(
            "ALTER TABLE score_snapshots ALTER COLUMN challenge_points TYPE NUMERIC(14, 4) "
            "USING challenge_points::numeric;"
        )
        cur.execute(
            "ALTER TABLE score_snapshots ALTER COLUMN service_total TYPE NUMERIC(14, 4) USING service_total::numeric;"
        )
        cur.execute("ALTER TABLE scores ALTER COLUMN sla_points SET DEFAULT 1;")
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_submissions_submitter_round_result
            ON submissions(submitter_team_id, round_id, result);
            """
        )

        for team_name in all_teams:
            is_nop = team_name == nop_name
            submit_token = f"{token_prefix}{team_name}"
            nat_alias = f"{team_name}-nat"
            country_code = team_countries.get(team_name, default_country)
            cur.execute(
                """
                INSERT INTO teams (name, submit_token, nat_alias, is_nop, country_code)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (name)
                DO UPDATE SET
                    submit_token = EXCLUDED.submit_token,
                    nat_alias = EXCLUDED.nat_alias,
                    is_nop = EXCLUDED.is_nop,
                    country_code = EXCLUDED.country_code
                RETURNING id, is_nop;
                """,
                (team_name, submit_token, nat_alias, is_nop, country_code),
            )
            team_row = cur.fetchone()
            team_id = team_row["id"]
            # Component scoring starts all challenge components at 0; SLA ratio
            # defaults to 1.0 until the first check completes.
            cur.execute(
                """
                INSERT INTO scores (
                    team_id, attack_points, defense_points, uptime_points,
                    hacked_penalty_points, challenge_points, sla_points, total
                )
                VALUES (%s, 0, 0, 0, 0, 0, 1, 0)
                ON CONFLICT (team_id) DO NOTHING;
                """,
                (team_id,),
            )

        service_ids: Dict[str, int] = {}
        for service_name in services:
            num_payloads = _payloads_for(service_name)
            display_name = _display_name_for(service_name)
            cur.execute(
                """
                INSERT INTO services (name, display_name, internal_port, num_payloads, flags_per_tick)
                VALUES (%s, %s, 8080, %s, %s)
                ON CONFLICT (name)
                DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    internal_port = EXCLUDED.internal_port,
                    num_payloads = EXCLUDED.num_payloads,
                    flags_per_tick = EXCLUDED.flags_per_tick
                RETURNING id;
                """,
                (service_name, display_name, num_payloads, num_payloads),
            )
            service_ids[service_name] = cur.fetchone()["id"]

        cur.execute("SELECT id, name FROM teams;")
        team_rows = cur.fetchall()
        for team_row in team_rows:
            team_id = team_row["id"]
            team_name = team_row["name"]
            for index, service_name in enumerate(services):
                host, port = _host_for_team_service(team_name, service_name, nop_name, index)
                cur.execute(
                    """
                    INSERT INTO team_services (team_id, service_id, host, port, enabled)
                    VALUES (%s, %s, %s, %s, TRUE)
                    ON CONFLICT (team_id, service_id)
                    DO UPDATE SET host = EXCLUDED.host, port = EXCLUDED.port, enabled = TRUE;
                    """,
                    (team_id, service_ids[service_name], host, port),
                )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS log_messages (
                id BIGSERIAL PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                component TEXT NOT NULL,
                level INTEGER NOT NULL DEFAULT 5,
                title TEXT NOT NULL,
                text TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_log_messages_created ON log_messages(created_at DESC);
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS game_state (
                id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                state TEXT NOT NULL DEFAULT 'STOPPED',
                desired_state TEXT NOT NULL DEFAULT 'STOPPED',
                current_tick INTEGER NOT NULL DEFAULT 0,
                tick_start BIGINT,
                tick_end BIGINT,
                start_at BIGINT,
                stop_after_tick INTEGER,
                scoreboard_freeze_tick INTEGER,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )

        cur.execute(
            """
            WITH latest AS (
                SELECT DISTINCT ON (team_id, service_id)
                    team_id, service_id, off_points, def_points, sla_points, tick
                FROM team_tick_points
                ORDER BY team_id, service_id, tick DESC
            ),
            per_team AS (
                SELECT
                    team_id,
                    SUM(off_points) AS attack_points,
                    SUM(def_points) AS defense_points,
                    SUM(sla_points) AS sla_points,
                    SUM(off_points + def_points) AS challenge_points,
                    SUM((off_points + def_points) * sla_points) AS total
                FROM latest
                GROUP BY team_id
            )
            UPDATE scores sc
            SET attack_points = COALESCE(p.attack_points, sc.attack_points, 0),
                defense_points = COALESCE(p.defense_points, sc.defense_points, 0),
                uptime_points = COALESCE(p.sla_points, sc.uptime_points, 0),
                hacked_penalty_points = 0,
                challenge_points = COALESCE(p.challenge_points, sc.attack_points + sc.defense_points, 0),
                sla_points = CASE WHEN svc.service_count = 0 THEN 0
                                  ELSE COALESCE(p.sla_points, sc.sla_points * svc.service_count, 0)
                                       / svc.service_count END,
                total = COALESCE(p.total, (sc.attack_points + sc.defense_points) * sc.sla_points, 0),
                updated_at = NOW()
            FROM teams t
            LEFT JOIN per_team p ON p.team_id = t.id
            CROSS JOIN (SELECT COUNT(*)::numeric AS service_count FROM services) svc
            WHERE sc.team_id = t.id;
            """
        )
