"""The central "my team" page, including all functionality accessible from there."""

import hashlib
from pathlib import Path
from subprocess import check_call
from tempfile import NamedTemporaryFile
from typing import cast

from constance import config
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.forms import ModelForm
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
)
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from mainpage import vmhosting
from mainpage.models import KeySlot, Peer, Player, ServiceToken, TeamProfile
from mainpage.network_lib import (
    get_team_ip,
    get_wireguard_config,
    set_team_cloudhosting_status,
)
from mainpage.utils import captain_required, player_required, technician_required


@require_GET
@login_required
@player_required
def team(request: HttpRequest, player: Player) -> HttpResponse:
    # Captain can't sign in until he confirms the team
    # Player's can't join until the captain logged in to get the join link
    # => This team must have a team_id
    team_id = cast(int, player.team.team_id)

    players: list[Player] = []
    if player.is_at_least_technician:
        players = list(
            Player.objects.filter(team=player.team).order_by("username").all()
        )

    service_tokens = ServiceToken.objects.filter(is_visible=True).order_by("name").all()
    for token in service_tokens:
        token.set_token(team_id)

    context = {
        "player": player,
        "team": player.team,
        "team_id": team_id,
        "join_link": request.build_absolute_uri(
            reverse("signup_player", args=(player.team.join_token,))
        ),
        "show_config": config.SHOW_CONFIG,
        "subnet": get_team_ip(team_id, "0/24"),
        "vulnbox_ip": get_team_ip(team_id, "2"),
        "exploiter_ip": get_team_ip(team_id, "3"),
        "vms": vmhosting.get_vms_for_view(request),
        "service_tokens": service_tokens,
        "players": players,
    }
    return render(request, "team.html", context=context)


@login_required
def vpn_config_download(request: HttpRequest, key_slot_id: int) -> HttpResponse:
    key_slot = KeySlot.objects.filter(pk=key_slot_id).first()
    if key_slot is None:
        return HttpResponseBadRequest("Invalid ID")
    # check permissions
    if key_slot.owner_id != request.user.id:
        # check if the user is technician from the same team
        player = Player.objects.filter(id=request.user.id).first()
        if player is None or not player.is_at_least_technician:
            return HttpResponseForbidden("Not your key")
        if key_slot.owner is None or player.team_id != key_slot.owner.team_id:
            return HttpResponseForbidden("Not your key")
    # check peer
    peer = Peer.objects.filter(key_slot=key_slot, enabled=True).first()
    if not peer:
        return HttpResponseBadRequest("Key is not active")
    peer.key_slot = key_slot
    config_file = get_wireguard_config(peer)
    response = HttpResponse(content=config_file, content_type="text/plain")
    response["Content-Disposition"] = "attachment; filename=ctf-vpn.conf"
    return response


class TeamChangeForm(ModelForm):
    class Meta:
        model = TeamProfile
        fields = ("affiliation", "website", "irc_name")


@require_POST
@login_required
@player_required
@technician_required
def team_change(request: HttpRequest, player: Player) -> HttpResponse:
    new_irc_name = request.POST.get("new_irc", None)
    new_affiliation = request.POST.get("new_affiliation", None)
    new_web_site = request.POST.get("new_web_site", None)
    if None in [new_affiliation, new_web_site, new_irc_name]:
        messages.error(request, "Missing arguments for Profile change!")
        return HttpResponse("Bad Request", status=400)
    try:
        team = player.team
        team.affiliation = new_affiliation
        team.irc_name = new_irc_name
        team.website = new_web_site
        team.save()
        messages.success(request, "Successfully changed Team Information")
    except Exception as e:
        print("EXCEPTION in team_change:\n", e)
        messages.error(request, "Error during Profile change!")
        return HttpResponse("Internal Server Error", status=500)
    return HttpResponse("Success", status=200)


@require_POST
@login_required
@player_required
def team_new_logo(request: HttpRequest, player: Player) -> HttpResponse:
    if "new_logo" not in request.FILES:
        messages.error(request, "New logo is missing!")
        return redirect(reverse("team"))
    new_logo = cast(UploadedFile, request.FILES["new_logo"])

    file_system_storage = FileSystemStorage()

    team = player.team
    hashlib.md5(team.name.encode("utf-8")).hexdigest()

    try:
        with NamedTemporaryFile() as tmp_file:
            with NamedTemporaryFile() as logo_temp_path:
                for chunk in new_logo.chunks():
                    tmp_file.write(chunk)
                tmp_file.seek(0)
                # ImageMagick 7 command line
                cmd = [
                    "magick",
                    "convert",
                    tmp_file.name,
                    "-resize",
                    "1000x1000",
                    logo_temp_path.name,
                ]
                try:
                    check_call(cmd)
                except FileNotFoundError:
                    check_call(cmd[1:])  # imagemagick 6 interface
                final_logo: bytes = Path(logo_temp_path.name).read_bytes()
                logo_hashed_name = hashlib.md5(
                    final_logo, usedforsecurity=False
                ).hexdigest()
                logo_file_name = file_system_storage.save(
                    f"{logo_hashed_name}.png", logo_temp_path
                )
        team.logo = logo_file_name
        team.save()
        messages.success(request, "Successfully changed Team Icon")
    except Exception as e:
        print("EXCEPTION in logo_change:\n", e)
        messages.error(request, "Error during Profile Logo change!")
        return redirect(reverse("team"))
    return redirect(reverse("team"))


@require_POST
@login_required
@player_required
@technician_required
def team_change_hosting(request: HttpRequest, player: Player) -> HttpResponse:
    if player.team:
        use_cloudhosting = request.POST["use_cloudhosting"] == "true"
        with transaction.atomic():
            msgs = set_team_cloudhosting_status(player.team, use_cloudhosting)
        messages.success(request, "\n".join(msgs))
    else:
        messages.error(request, "Invalid team")
    return redirect(reverse(team))


@require_POST
@login_required
@player_required
@captain_required
def player_change_role(request: HttpRequest, player: Player) -> HttpResponse:
    role = Player.RoleChoices(request.POST["role"])
    target_player: Player = Player.objects.filter(
        team_id=player.team_id, pk=request.POST["id"]
    ).get()
    target_player.role = role
    target_player.save()
    messages.success(
        request,
        f"Successfully changed role of {target_player.username} to {role.name.lower()}",
    )
    return redirect(reverse(team))


@require_POST
@login_required
@player_required
@captain_required
def player_delete(request: HttpRequest, player: Player) -> HttpResponse:
    target_player: Player = Player.objects.filter(
        team_id=player.team_id, pk=request.POST["id"]
    ).get()
    with transaction.atomic():
        KeySlot.objects.filter(owner=target_player).delete()
        target_player.delete()
    messages.success(
        request,
        f'Successfully deleted member "{target_player.username}" and all its keys',
    )
    return redirect(reverse(team))
