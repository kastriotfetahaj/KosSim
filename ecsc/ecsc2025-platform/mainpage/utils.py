import subprocess
from functools import wraps

from constance import config
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse

from mainpage.models import Player


def get_player_from_request(request) -> Player:
    if not (request.user and request.user.is_authenticated):
        raise PermissionDenied
    try:
        player = Player.objects.get(id=request.user.id)
    except Player.DoesNotExist:
        raise PermissionDenied

    return player


def player_required(view_func):
    """Get the player from a request's user."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        player = get_player_from_request(request)
        return view_func(request, *args, player=player, **kwargs)

    return wrapper


def technician_required(view_func):
    """Authorize request only if player role is technician (or higher)."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        player = get_player_from_request(request)
        if not player.is_at_least_technician:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapper


def captain_required(view_func):
    """Authorize request only if player role is technician (or higher)."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        player = get_player_from_request(request)
        if not player.is_captain:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapper


def superuser_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_superuser:
            return HttpResponse("", status=403)
        return view_func(request, *args, **kwargs)

    return wrapper


def hosting_token_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if (
            not config.HOSTING_TOKEN
            or "token" not in request.GET
            or config.HOSTING_TOKEN != request.GET["token"]
        ):
            return HttpResponse("Invalid token (or no token configured)", status=403)
        return view_func(request, *args, **kwargs)

    return wrapper


def gen_wg_keypair() -> tuple[str, str]:
    privkey = subprocess.check_output(["wg", "genkey"]).decode("utf-8").strip()
    pubkey = (
        subprocess.check_output(["wg", "pubkey"], input=privkey.encode())
        .decode("utf-8")
        .strip()
    )
    return privkey, pubkey
