from django.core.management import BaseCommand
from django.db import transaction

from mainpage.models import Interface, Peer, TeamProfile


def patch_team_id_in_ip(ip: str, team_id: int) -> str:
    parts = ip.split(".")
    parts[1] = str(32 + (team_id // 200))
    parts[2] = str(team_id % 200)
    return ".".join(parts)


class Command(BaseCommand):
    """USAGE: python3 manage.py make-nop <teamname>."""

    def add_arguments(self, parser):
        parser.add_argument("team_name", type=str, default="NOP")

    def handle(self, *args, **options) -> None:
        with transaction.atomic():
            team: TeamProfile = TeamProfile.objects.filter(
                name=options["team_name"]
            ).get()
            if team.team_id is None:
                raise ValueError("Please activate NOP team!")
            team.team_id = 1
            team.save()
            interface = Interface.objects.filter(team=team).get()
            interface.cidr = patch_team_id_in_ip(interface.cidr, 1)
            interface.save()
            for peer in Peer.objects.filter(interface=interface).all():
                peer.cidr = patch_team_id_in_ip(peer.cidr, 1)
                peer.save()
        print(f"Team {team.name} turned to NOP team.")
