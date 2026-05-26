from datetime import datetime, timedelta, timezone
from json import loads
from logging import getLogger
from pathlib import Path
from secrets import token_hex

from django.contrib.auth.hashers import make_password
from django.core.management import BaseCommand
from django.db import transaction
from django_q.tasks import Schedule, schedule

from mainpage.models import Player, TeamProfile, User

LOGGER = getLogger(__name__)


def _create_team(team_name, username, affiliation, email, password):
    team = TeamProfile(
        name=team_name, affiliation=affiliation, is_active=True, use_cloudhosting=True
    )
    team.save()

    password_hash = make_password(password, hasher="md5")
    captain = Player(
        username=username,
        email=email,
        team=team,
        is_active=True,
        password=password_hash,
    )
    captain.role = Player.RoleChoices.CAPTAIN
    captain.save()

    team.confirm_team()


class Command(BaseCommand):
    """
    Import teams into the platform.

    USAGE: manage.py import_teams <file>
    """

    help = "Import teams with coach names and affiliations"

    def add_arguments(self, parser):
        parser.add_argument("file", type=Path)
        parser.add_argument("--add-teams", action="store_true", default=False)

    def handle(self, *args, file: Path, add_teams=False, **options):
        _ = (args, options)  # unused
        user, created = User.objects.get_or_create(username="admin")
        if created:
            user.is_staff = user.is_superuser = True
            password = token_hex(16)
            user.set_password(password)
            user.save()
            LOGGER.info(f"Created superuser(admin:{password})")

        contents: dict[str, dict[str, str]] = loads(file.read_text())
        with transaction.atomic():
            for _, team_contents in contents.items():
                team_name = team_contents["team"]
                username = team_contents["username"]
                password = team_contents["password"]
                email = f"{username}@ecsc.local"

                _create_team(
                    team_name=team_name,
                    username=username,
                    affiliation=team_name,
                    email=email,
                    password=password,
                )
                LOGGER.info("Imported team %s", team_name)
        # Run one minute later, i.e., now + 1
        schedule(
            "django.core.management.call_command",
            "ensure_peers",
            schedule_type=Schedule.MINUTES,
            minutes=1,
            next_run=datetime.now(tz=timezone.utc) + timedelta(minutes=1),
        )
