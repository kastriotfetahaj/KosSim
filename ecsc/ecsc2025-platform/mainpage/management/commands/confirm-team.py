from django.core.management import BaseCommand
from django.db import transaction

from mainpage.models import TeamProfile


class Command(BaseCommand):
    """USAGE: python3 manage.py confirm-team <teamname>."""

    def add_arguments(self, parser):
        parser.add_argument("team_name", type=str)

    def handle(self, *args, **options) -> None:
        with transaction.atomic():
            team: TeamProfile = TeamProfile.objects.filter(
                name=options["team_name"]
            ).get()
            team.confirm_team()
        print(f"Team {team.name} confirmed.")
