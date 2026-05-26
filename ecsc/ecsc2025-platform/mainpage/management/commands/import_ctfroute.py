import json
import logging
from abc import ABC
from datetime import datetime, timedelta, timezone
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path
from typing import Any, Optional

from constance import config
from django.core.management import BaseCommand
from django.db import transaction
from django_q.tasks import Schedule, schedule
from pydantic import BaseModel, ConfigDict

from mainpage import models

LOGGER = logging.getLogger(__name__)

NUM_INFRA_CONFIGS = 10


class CtfRouteBaseModel(BaseModel, ABC):
    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
    )


class WireGuardPeer(CtfRouteBaseModel):
    cidr: IPv4Network
    public_key: str
    private_key: Optional[str] = None
    vpn_host: Optional[str] = None
    vpn_port: Optional[int] = None
    overrides: Optional[dict[str, Any]] = None


class TeamNetInfo(CtfRouteBaseModel):
    id: str
    vpn_host: str
    vpn_port: int
    vpn_public_key: str
    vulnbox: IPv4Address | None = None
    exploiter: IPv4Address | None = None
    gateway: IPv4Address | None = None
    peers: list[WireGuardPeer]


class CTFRouteNetInfo(CtfRouteBaseModel):
    game_net: str
    teams: list[TeamNetInfo]


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "webpage_json",
            type=Path,
            help="webpage ctfroute config",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Reset entire network configuration",
        )

    def handle(self, webpage_json: Path, *args, reset: bool, **options):
        raw_config = json.loads(webpage_json.read_text())
        ctfroute_config = CTFRouteNetInfo.model_validate(raw_config)

        if reset:
            confirm = input(
                "Are you sure you want to reset the entire network configuration? [y/N]"
            )
            if confirm.lower() not in ("y", "yes"):
                LOGGER.info("Aborting.")
                exit(0)
            models.KeySlot.objects.all().delete()

        config.VPN_GAME_NET = ctfroute_config.game_net

        for team in ctfroute_config.teams:
            if team.id == "orga":
                continue
            if not team.id.isnumeric():
                LOGGER.warning(f"Team id {team.id} is not numeric! Ignoring!")
                continue

            team_id = int(team.id)

            try:
                interface = models.Interface.objects.get(team__team_id=team_id)
            except models.Interface.DoesNotExist:
                # TODO: Check where we create interfaces?
                LOGGER.warning(f"Team id {team.id} has no interface! Ignoring!")
                continue

            interface.vpn_port = team.vpn_port
            interface.vpn_host = team.vpn_host
            interface.public_key = team.vpn_public_key
            interface.managed = True
            interface.cidr = team.gateway
            interface.save()

            vulnbox_peer_conf: WireGuardPeer | None = None
            exploiter_peer_conf: WireGuardPeer | None = None
            pool_peers = []
            for peer_conf in team.peers:
                if team.vulnbox in peer_conf.cidr:
                    vulnbox_peer_conf = peer_conf
                    continue
                if team.exploiter in peer_conf.cidr:
                    exploiter_peer_conf = peer_conf
                    continue

                if not models.KeySlot.objects.filter(
                    public_key=peer_conf.public_key
                ).exists():
                    pool_peers.append(peer_conf)

            assert vulnbox_peer_conf is not None
            assert exploiter_peer_conf is not None

            for kind, cloud_peer_conf in [
                (models.Peer.TypeChoices.VULNBOX, vulnbox_peer_conf),
                (models.Peer.TypeChoices.EXPLOITER, exploiter_peer_conf),
            ]:
                if not models.KeySlot.objects.filter(
                    public_key=cloud_peer_conf.public_key
                ).exists():
                    cloud_key_slot = models.KeySlot(
                        owner=None,
                        name=f"{kind.label} of team {team_id}",
                        public_key=cloud_peer_conf.public_key,
                        private_key=cloud_peer_conf.private_key,
                        managed=True,
                    )
                    cloud_key_slot.save()
                    cloud_peer = models.Peer(
                        interface=interface,
                        cidr=cloud_peer_conf.cidr,
                        vpn_host=cloud_peer_conf.vpn_host,
                        vpn_port=cloud_peer_conf.vpn_port,
                        key_slot=cloud_key_slot,
                        overrides=cloud_peer_conf.overrides,
                        managed=True,
                        enabled=True,
                        type=kind,
                    )
                    cloud_peer.save()

            captain = models.Player.objects.filter(
                team__team_id=team_id, role=models.Player.RoleChoices.CAPTAIN
            ).get()

            for idx, peer_conf in enumerate(pool_peers):
                if (
                    not peer_conf
                    or models.KeySlot.objects.filter(
                        public_key=peer_conf.public_key
                    ).exists()
                ):
                    continue

                with transaction.atomic():
                    if idx < NUM_INFRA_CONFIGS:
                        cloud_key_slot = models.KeySlot(
                            owner=captain,
                            name="Pregenerated config for team infra",
                            public_key=peer_conf.public_key,
                            private_key=peer_conf.private_key,
                            managed=True,
                        )
                        cloud_key_slot.save()

                        cloud_peer = models.Peer(
                            interface=interface,
                            cidr=peer_conf.cidr,
                            vpn_host=peer_conf.vpn_host,
                            vpn_port=peer_conf.vpn_port,
                            key_slot=cloud_key_slot,
                            overrides=cloud_peer_conf.overrides,
                            managed=True,
                            type=models.Peer.TypeChoices.AUTOIP,
                        )
                    else:
                        cloud_key_slot = models.KeySlot(
                            owner=None,
                            name=f"Pregenerated config for team {team_id}",
                            public_key=peer_conf.public_key,
                            private_key=peer_conf.private_key,
                            managed=True,
                        )
                        cloud_key_slot.save()

                        cloud_peer = models.Peer(
                            interface=interface,
                            cidr=peer_conf.cidr,
                            vpn_host=peer_conf.vpn_host,
                            vpn_port=peer_conf.vpn_port,
                            key_slot=cloud_key_slot,
                            managed=True,
                            enabled=False,
                            type=models.Peer.TypeChoices.PREPARED_POOL,
                        )
                    cloud_peer.save()

        # Run one minute later, i.e., now + 1
        schedule(
            "django.core.management.call_command",
            "ensure_peers",
            schedule_type=Schedule.MINUTES,
            minutes=1,
            next_run=datetime.now(tz=timezone.utc) + timedelta(minutes=1),
        )
