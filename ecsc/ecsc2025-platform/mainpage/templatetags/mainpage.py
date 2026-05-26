import datetime
import json
from typing import Any
from urllib.parse import urljoin

from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.template import Library
from django.utils.safestring import mark_safe

from mainpage.models import TeamProfile

register = Library()


@register.filter(name="json")
def json_dumps(data: Any) -> str:
    return mark_safe(json.dumps(data))


@register.simple_tag(name="team_logo", takes_context=True)
def team_logo(context, team: TeamProfile) -> str:
    request: WSGIRequest = context["request"]
    host = f"{request.get_host()}"
    if hasattr(settings, "MEDIA_SUBDOMAIN"):
        host = f"{settings.MEDIA_SUBDOMAIN}.{host}"
    if team.logo:
        return urljoin(
            urljoin(f"{request.scheme}://{host}", settings.MEDIA_URL), team.logo
        )
    return settings.STATIC_URL + "img/profile_dummy.png"


@register.simple_tag(name="date_day")
def date_day(date: datetime.datetime) -> str:
    return date.strftime("%A, %B %d, %Y")


@register.simple_tag(name="date_time")
def date_time(date: datetime.datetime) -> str:
    return date.strftime("%H:%M %Z")


@register.simple_tag(name="date_full")
def date_full(date: datetime.datetime) -> str:
    return date.strftime("%Y-%m-%d %H:%M %Z")


@register.simple_tag(name="date_8601")
def date_8601(date: datetime.datetime) -> str:
    return date.strftime("%Y-%m-%dT%H:%M:%S%z")


@register.simple_tag(name="game_addr", takes_context=True)
def game_addr(context, tmpl: str) -> str:
    if context.get("team_id"):
        return tmpl.replace("<TEAM>", str(context["team_id"]))
    return tmpl
