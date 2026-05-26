from constance import config
from django.conf import settings
from django.http import HttpRequest
from loginas.utils import is_impersonated_session


def template_settings(request: HttpRequest) -> dict:
    return {
        "ctf": config.CTF_META,
        "config": config,
        "show_scoreboard": config.SHOW_SCOREBOARD,
        "url_scoreboard": config.URL_SCOREBOARD,
        "is_impersonated_session": is_impersonated_session(request),
        "site_environment": settings.ENVIRONMENT,
    }
