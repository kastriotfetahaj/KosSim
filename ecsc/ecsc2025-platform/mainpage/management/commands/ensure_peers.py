from logging import getLogger

from constance import config
from django.core.management import BaseCommand
from django.db import transaction
from django.db.models import Count, Q

from mainpage import models

LOGGER = getLogger(__name__)


class Command(BaseCommand):
    """USAGE: python3 manage.py ensure_peers."""

    # def add_arguments(self, parser):
    #     parser.add_argument("team_name",type=str)

    def handle(self, *args, **options) -> None:
        for team in models.TeamProfile.objects.all():
            pregenerated_pool = list(
                models.Peer.objects.filter(
                    type=models.Peer.TypeChoices.PREPARED_POOL,
                    interface__team=team,
                )
            )
            for player in (
                models.Player.objects.annotate(
                    num_peers=Count(
                        "keyslots__peers",
                        filter=Q(
                            keyslots__peers__type="AI",
                            keyslots__name__contains="ersonal",
                        ),
                    )
                )
                .filter(
                    team=team,
                    num_peers__lt=config.VPN_MANGED_PLAYER_CONFIGS,
                )
                .order_by("pk")
            ):
                for i in range(player.num_peers, config.VPN_MANGED_PLAYER_CONFIGS):
                    try:
                        peer: models.Peer = pregenerated_pool.pop()
                    except IndexError:
                        LOGGER.warning(f"Ran out of peers for team {team.id}!")
                        break
                    LOGGER.info(
                        f"Setting up {peer.cidr} for {player.username} of {player.team.name}"
                    )
                    with transaction.atomic():
                        peer.type = models.Peer.TypeChoices.AUTOIP
                        peer.enabled = True
                        peer.save()

                        keyslot: models.KeySlot = peer.key_slot
                        keyslot.name = f"Personal key #{i + 1} for {player.username}"
                        keyslot.owner = player
                        keyslot.save()
