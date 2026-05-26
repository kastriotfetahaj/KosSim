"""Public JSON feeds: /api/teams.json and /api/attack.json."""

from __future__ import annotations

import os
from typing import Any, Dict, List

from .db import get_cursor
from .flag_crypto import flag_regex_pattern
from .game_timer import load_timer


def _team_vulnbox_ip(cur: Any, team_id: int, team_name: str) -> str:
    from .init_db import _parse_map

    ip_map = _parse_map(os.getenv("TEAM_VULNBOX_IP_MAP", ""))
    if team_name in ip_map:
        return ip_map[team_name]
    cur.execute(
        """
        SELECT host FROM team_services
        WHERE team_id = %s AND enabled = TRUE
        ORDER BY service_id ASC LIMIT 1;
        """,
        (team_id,),
    )
    row = cur.fetchone()
    if row and row["host"]:
        return str(row["host"])
    return f"{team_name}-nat"


def _list_player_teams(cur: Any) -> List[Dict[str, Any]]:
    cur.execute(
        """
        SELECT id, name, country_code, nat_alias
        FROM teams
        WHERE is_nop = FALSE
        ORDER BY id ASC;
        """
    )
    teams: List[Dict[str, Any]] = []
    for row in cur.fetchall():
        tid = int(row["id"])
        name = row["name"]
        teams.append({
            "id": tid,
            "name": name,
            "ip": _team_vulnbox_ip(cur, tid, name),
            "country_code": row["country_code"],
            "nat_alias": row["nat_alias"],
        })
    return teams


def build_teams_json() -> Dict[str, Any]:
    with get_cursor(commit=False) as (_conn, cur):
        return {"teams": _list_player_teams(cur)}


def build_attack_json() -> Dict[str, Any]:
    with get_cursor(commit=False) as (_conn, cur):
        timer = load_timer(cur)
        latest_tick = max(1, timer.current_tick)
        teams_out = _list_player_teams(cur)

        cur.execute(
            """
            SELECT t.id AS team_id, t.name AS team_name, s.name AS service_name,
                   f.payload, f.attack_info
            FROM flags f
            JOIN teams t ON t.id = f.team_id
            JOIN services s ON s.id = f.service_id
            JOIN flag_rounds fr ON fr.round_id = f.round_id
            WHERE fr.tick = %s AND t.is_nop = FALSE
            ORDER BY s.name ASC, t.id ASC, f.payload ASC;
            """,
            (latest_tick,),
        )
        flag_ids: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for row in cur.fetchall():
            svc = row["service_name"]
            ip = _team_vulnbox_ip(cur, int(row["team_id"]), row["team_name"])
            tick_key = str(latest_tick)
            bucket = flag_ids.setdefault(svc, {}).setdefault(ip, {})
            infos = bucket.get(tick_key)
            info = row["attack_info"]
            if infos is None:
                bucket[tick_key] = info
            elif isinstance(infos, list):
                infos.append(info)
            else:
                bucket[tick_key] = [infos, info]

    return {
        "flag_regex": flag_regex_pattern(),
        "teams": teams_out,
        "flag_ids": flag_ids,
        "current_tick": latest_tick,
    }
