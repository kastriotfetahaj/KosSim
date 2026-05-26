"""Endpoints for our various scripts, which are not part of a django-restful API."""

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, JsonResponse

from mainpage.models import TeamProfile
from mainpage.utils import hosting_token_required


@hosting_token_required
def teams_export(request: HttpRequest) -> HttpResponse:
    teams = TeamProfile.objects.filter(is_active=True, team_id__isnull=False).all()
    data = [
        {
            "id": team.team_id,
            "name": team.name,
            "affiliation": team.affiliation or None,
            "website": team.website or None,
            "logo": team.logo or None,
        }
        for team in teams
    ]
    return JsonResponse({"teams": data})


def debug(request: HttpRequest) -> HttpResponse:
    if not settings.DEBUG:
        raise PermissionDenied()
    return JsonResponse(
        {
            "headers": dict(request.headers.items()),
            "url": request.build_absolute_uri(),
        }
    )
