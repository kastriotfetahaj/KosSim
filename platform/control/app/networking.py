"""WireGuard and nftables artifact generation for competition routing."""

from __future__ import annotations

import base64
import ipaddress
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple


@dataclass(frozen=True)
class TeamNetworkPlan:
    team_id: int
    team_name: str
    team_cidr: str
    gateway_ip: str
    vulnbox_ip: str
    player_ip: str
    player_private_key: str
    player_public_key: str


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def generate_wg_keypair() -> Tuple[str, str]:
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import x25519

        private = x25519.X25519PrivateKey.generate()
        public = private.public_key()
        private_raw = private.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_raw = public.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return _b64(private_raw), _b64(public_raw)
    except Exception:
        raw = os.urandom(32)
        return _b64(raw), _b64(__import__("hashlib").sha256(raw).digest())


def default_team_network(team_id: int) -> Tuple[str, str, str, str]:
    if team_id < 1 or team_id > 250:
        raise ValueError("default team network supports team ids 1..250")
    net = ipaddress.ip_network(f"10.32.{team_id}.0/24")
    return str(net), str(net[254]), str(net[2]), str(net[10])


def checker_cidr() -> str:
    return os.getenv("CHECKER_CIDR", "10.32.250.0/24")


def control_public_cidr() -> str:
    return os.getenv("CONTROL_PUBLIC_CIDR", "10.32.251.2/32")


def router_endpoint() -> str:
    return os.getenv("ROUTER_WG_ENDPOINT", "router-public-ip:51820")


def router_listen_port() -> int:
    return int(os.getenv("ROUTER_WG_PORT", "51820"))


def control_public_ports() -> List[int]:
    raw = os.getenv("CONTROL_PUBLIC_PORTS", "80,443,1337")
    ports: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            ports.append(int(part))
    return ports or [80, 443, 1337]


def ensure_network_state(cur: Any) -> None:
    cur.execute("SELECT key, value FROM network_settings;")
    settings = {row["key"]: row["value"] for row in cur.fetchall()}
    if "router_private_key" not in settings or "router_public_key" not in settings:
        private, public = generate_wg_keypair()
        cur.execute(
            """
            INSERT INTO network_settings (key, value)
            VALUES ('router_private_key', %s), ('router_public_key', %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();
            """,
            (private, public),
        )
    for key, value in (
        ("checker_cidr", checker_cidr()),
        ("control_public_cidr", control_public_cidr()),
        ("router_endpoint", router_endpoint()),
        ("router_listen_port", str(router_listen_port())),
        ("control_public_ports", ",".join(str(p) for p in control_public_ports())),
    ):
        cur.execute(
            """
            INSERT INTO network_settings (key, value)
            VALUES (%s, %s)
            ON CONFLICT (key) DO NOTHING;
            """,
            (key, value),
        )

    cur.execute("SELECT id, name FROM teams ORDER BY id;")
    for row in cur.fetchall():
        team_id = int(row["id"])
        team_cidr, gateway_ip, vulnbox_ip, player_ip = default_team_network(team_id)
        private, public = generate_wg_keypair()
        cur.execute(
            """
            INSERT INTO team_networks (
                team_id, team_cidr, gateway_ip, vulnbox_ip, player_ip,
                player_private_key, player_public_key
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (team_id) DO NOTHING;
            """,
            (team_id, team_cidr, gateway_ip, vulnbox_ip, player_ip, private, public),
        )


def load_network_plans(cur: Any) -> Tuple[Dict[str, str], List[TeamNetworkPlan]]:
    ensure_network_state(cur)
    cur.execute("SELECT key, value FROM network_settings;")
    settings = {row["key"]: row["value"] for row in cur.fetchall()}
    cur.execute(
        """
        SELECT tn.*, t.name AS team_name
        FROM team_networks tn
        JOIN teams t ON t.id = tn.team_id
        ORDER BY tn.team_id ASC;
        """
    )
    plans = [
        TeamNetworkPlan(
            team_id=int(row["team_id"]),
            team_name=row["team_name"],
            team_cidr=row["team_cidr"],
            gateway_ip=row["gateway_ip"],
            vulnbox_ip=row["vulnbox_ip"],
            player_ip=row["player_ip"],
            player_private_key=row["player_private_key"],
            player_public_key=row["player_public_key"],
        )
        for row in cur.fetchall()
    ]
    return settings, plans


def _set_elements(values: Iterable[str]) -> str:
    items = [str(v) for v in values]
    return ", ".join(items) if items else "0.0.0.0/32"


def render_nftables(settings: Dict[str, str], plans: List[TeamNetworkPlan]) -> str:
    team_cidrs = [p.team_cidr for p in plans]
    vulnboxes = [p.vulnbox_ip for p in plans]
    public_ports = settings.get("control_public_ports", "80,443,1337").replace(",", ", ")
    same_team_rules = "\n".join(
        f"        ip saddr {p.team_cidr} ip daddr {p.team_cidr} accept"
        for p in plans
    )
    other_vulnbox_rules = "\n".join(
        f"        ip saddr {p.team_cidr} ip daddr != {p.team_cidr} ip daddr @vulnboxes accept"
        for p in plans
    )
    return f"""#!/usr/sbin/nft -f
flush table inet kossim_acl

table inet kossim_acl {{
    set team_nets {{
        type ipv4_addr
        flags interval
        elements = {{ {_set_elements(team_cidrs)} }}
    }}

    set vulnboxes {{
        type ipv4_addr
        elements = {{ {_set_elements(vulnboxes)} }}
    }}

    set checker_nets {{
        type ipv4_addr
        flags interval
        elements = {{ {settings.get("checker_cidr", checker_cidr())} }}
    }}

    set control_public {{
        type ipv4_addr
        flags interval
        elements = {{ {settings.get("control_public_cidr", control_public_cidr())} }}
    }}

    chain forward {{
        type filter hook forward priority filter; policy drop;
        ct state established,related accept
        ip saddr @checker_nets ip daddr @team_nets accept
{same_team_rules}
{other_vulnbox_rules}
        ip saddr @team_nets ip daddr @control_public tcp dport {{ {public_ports} }} accept
        counter drop
    }}

    chain input {{
        type filter hook input priority filter; policy drop;
        iifname lo accept
        ct state established,related accept
        ip saddr @checker_nets accept
        udp dport {settings.get("router_listen_port", str(router_listen_port()))} accept
        meta l4proto icmp accept
        tcp dport 22 accept
        counter drop
    }}
}}
"""


def render_router_wg(settings: Dict[str, str], plans: List[TeamNetworkPlan]) -> str:
    peers = "\n".join(
        f"""
[Peer]
# {p.team_name}
PublicKey = {p.player_public_key}
AllowedIPs = {p.player_ip}/32
"""
        for p in plans
    )
    return f"""[Interface]
Address = {settings.get("control_public_cidr", control_public_cidr()).split("/")[0]}/32
ListenPort = {settings.get("router_listen_port", str(router_listen_port()))}
PrivateKey = {settings["router_private_key"]}

{peers.strip()}
"""


def render_team_client(settings: Dict[str, str], plan: TeamNetworkPlan) -> str:
    return f"""[Interface]
Address = {plan.player_ip}/32
PrivateKey = {plan.player_private_key}
DNS = {plan.gateway_ip}

[Peer]
PublicKey = {settings["router_public_key"]}
Endpoint = {settings.get("router_endpoint", router_endpoint())}
AllowedIPs = {plan.team_cidr}, {settings.get("control_public_cidr", control_public_cidr())}
PersistentKeepalive = 25
"""


def render_apply_script() -> str:
    return """#!/bin/sh
set -eu
install -d -m 700 /etc/wireguard
install -m 600 router/wg-kossim.conf /etc/wireguard/kossim.conf
nft -f router/nftables.nft
if command -v wg-quick >/dev/null 2>&1; then
  wg-quick down kossim >/dev/null 2>&1 || true
  wg-quick up kossim
fi
"""


def build_router_bundle(settings: Dict[str, str], plans: List[TeamNetworkPlan]) -> Dict[str, str]:
    files: Dict[str, str] = {
        "router/wg-kossim.conf": render_router_wg(settings, plans),
        "router/nftables.nft": render_nftables(settings, plans),
        "apply.sh": render_apply_script(),
    }
    for plan in plans:
        files[f"teams/{plan.team_name}.conf"] = render_team_client(settings, plan)
    return files
