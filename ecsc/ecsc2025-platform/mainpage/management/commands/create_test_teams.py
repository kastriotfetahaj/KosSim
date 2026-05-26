import logging
from random import seed

from constance import config
from django.contrib.auth.hashers import make_password
from django.core.management import BaseCommand
from django.db import transaction
from django.db.models import Max
from faker import Faker

from mainpage.models import Interface, KeySlot, Player, TeamProfile, User
from mainpage.network_lib import assign_next_free_ip_address, gen_wg_keypair

faker = Faker(["de", "pl_PL", "it_IT", "zh_CN"])


def _create_team():
    co = faker.unique.company()
    team = TeamProfile(
        name=co,
        affiliation=f"University of {faker.unique.city()}",
        is_active=True,
    )

    team.save()
    captain = _create_player(team)
    captain.role = Player.RoleChoices.CAPTAIN
    captain.save()

    team.confirm_team()
    team_interface = Interface.objects.get(team_id=team.id)
    player_amount = faker.random_int(2, 12)
    for i in range(player_amount):
        player = _create_player(team)
        player.save()
        if not config.VPN_DEFAULT_MANAGED:
            key_slot = KeySlot.objects.get(owner=player)
            if i % 10 < 7:
                _, pub = gen_wg_keypair()
                key_slot.public_key = pub
                key_slot.save()
            assign_next_free_ip_address(team, team_interface, key_slot)

    logging.info(f"Created Team {team.team_id} with {player_amount + 1} players")


def _create_player(team: TeamProfile) -> Player:
    username = faker.unique.user_name()
    player = Player(
        username=username,
        email=f"{username}@email.nowhere",
        team=team,
        is_active=True,
    )
    player.password = make_password(username, hasher="md5")
    return player


class Command(BaseCommand):
    """USAGE: manage.py create_test_teams <team_amount>."""

    help = "Creates test teams"

    def add_arguments(self, parser):
        parser.add_argument("team_amount", type=int)

    def handle(self, *args, **options):
        user, created = User.objects.get_or_create(username="admin")
        if created:
            user.is_staff = user.is_superuser = True
            user.set_password("admin")
            user.save()
            logging.info("Created superuser(admin:admin)")

        team_amount = options["team_amount"]
        max_team = (
            (TeamProfile.objects.aggregate(max_team_id=Max("team_id"))["max_team_id"])
            or 1
        )
        # Used to use seed 42
        Faker.seed(41 + max_team)
        seed(41 + max_team)
        with transaction.atomic():
            for _ in range(max_team + 1, max_team + team_amount + 1):
                _create_team()
        logging.info(f"Created {team_amount} teams")
