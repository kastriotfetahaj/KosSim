from __future__ import annotations

import datetime as dt

from ksapp.checker_jobs import should_retry_exception
from ksapp.networking import TeamNetworkPlan, build_router_bundle, render_nftables
from ksapp.observability import runtime_histogram
from ksapp.vulnboxes import docker_compose_command


def _plan(team_id: int, name: str) -> TeamNetworkPlan:
    return TeamNetworkPlan(
        team_id=team_id,
        team_name=name,
        team_cidr=f"10.32.{team_id}.0/24",
        gateway_ip=f"10.32.{team_id}.254",
        vulnbox_ip=f"10.32.{team_id}.2",
        player_ip=f"10.32.{team_id}.10",
        player_private_key=f"priv-{team_id}",
        player_public_key=f"pub-{team_id}",
    )


def test_checker_retry_stops_at_attempt_limit_and_deadline():
    now = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    assert should_retry_exception(
        attempt_no=1,
        max_attempts=2,
        deadline_at=now + dt.timedelta(seconds=10),
        now=now,
    )
    assert not should_retry_exception(
        attempt_no=2,
        max_attempts=2,
        deadline_at=now + dt.timedelta(seconds=10),
        now=now,
    )
    assert not should_retry_exception(
        attempt_no=1,
        max_attempts=2,
        deadline_at=now,
        now=now,
    )


def test_router_acl_drops_control_internals_by_default():
    settings = {
        "checker_cidr": "10.32.250.0/24",
        "control_public_cidr": "10.32.251.2/32",
        "control_public_ports": "80,443,1337",
        "router_private_key": "router-private",
        "router_public_key": "router-public",
        "router_endpoint": "router.example:51820",
        "router_listen_port": "51820",
    }
    nft = render_nftables(settings, [_plan(1, "team1"), _plan(2, "team2")])
    assert "policy drop" in nft
    assert "ip saddr @checker_nets ip daddr @team_nets accept" in nft
    assert "ip saddr 10.32.1.0/24 ip daddr != 10.32.1.0/24 ip daddr @vulnboxes accept" in nft
    assert "tcp dport { 80, 443, 1337 } accept" in nft
    assert "10.32.251.0/24" not in nft


def test_router_bundle_contains_team_profiles():
    settings = {
        "control_public_cidr": "10.32.251.2/32",
        "router_private_key": "router-private",
        "router_public_key": "router-public",
        "router_endpoint": "router.example:51820",
        "router_listen_port": "51820",
    }
    bundle = build_router_bundle(settings, [_plan(1, "team1")])
    assert "router/wg-kossim.conf" in bundle
    assert "router/nftables.nft" in bundle
    assert "teams/team1.conf" in bundle
    assert "PrivateKey = priv-1" in bundle["teams/team1.conf"]


def test_runtime_histogram_buckets_values_once():
    hist = runtime_histogram([0.1, 0.6, 9.0, 99.0])
    assert hist["0.25"] == 1
    assert hist["1.0"] == 1
    assert hist["10.0"] == 1
    assert hist["+Inf"] == 1


def test_docker_compose_command_targets_team_services(monkeypatch):
    monkeypatch.setenv("VULNBOX_COMPOSE_BIN", "docker compose")
    monkeypatch.setenv("VULNBOX_COMPOSE_PROJECT", "kossim")
    cmd = docker_compose_command("team7", "restart")
    assert cmd[:4] == ["docker", "compose", "-p", "kossim"]
    assert cmd[4:] == ["restart", "team7-svc1", "team7-svc2", "team7-svc3", "team7-svc4", "team7-svc5"]
