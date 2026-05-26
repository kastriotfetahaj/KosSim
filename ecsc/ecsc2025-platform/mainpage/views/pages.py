"""Public views with mostly constant content."""

from constance import config
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from mainpage.models import News, Player, TeamProfile
from mainpage.network_lib import get_team_ip


@require_GET
def index(request: HttpRequest) -> HttpResponse:
    news = News.objects.order_by("-created_at")
    if not request.user.is_superuser:
        news = news.filter(is_visible=True)
    news = news.all()
    return render(
        request,
        "index.html",
        context={
            "URL_ROUTER": config.URL_ROUTER,
            "URL_TESTBOX": config.URL_TESTBOX,
            "URL_VULNBOX": config.URL_VULNBOX,
            "URL_CLOUD": config.URL_CLOUD,
            "newslist": news,
        },
    )


@require_GET
def rules(request: HttpRequest) -> HttpResponse:
    return render(request, "rules.html")


@require_GET
def setup(request: HttpRequest) -> HttpResponse:
    try:
        player = Player.objects.get(id=request.user.id)
        team_id = player.team.team_id
    except Player.DoesNotExist:
        team_id = None

    return render(
        request,
        "setup.html",
        context={
            "team_id": team_id,
            "subnet": get_team_ip(team_id, "0/24")
            if team_id and config.SHOW_CONFIG
            else None,
            "netbase": get_team_ip(team_id, "")
            if team_id and config.SHOW_CONFIG
            else None,
        },
    )


@require_GET
def teams(request: HttpRequest) -> HttpResponse:
    all_teams = TeamProfile.objects.filter(is_active=True).order_by("team_id").all()
    return render(request, "teams.html", context={"teams": all_teams})
