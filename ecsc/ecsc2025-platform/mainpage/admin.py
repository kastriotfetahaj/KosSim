import traceback

from django.contrib import admin, messages
from django.db import models, transaction
from django.db.models import QuerySet
from django.forms.widgets import TextInput
from django.http import HttpRequest
from django.utils import timezone

from mainpage.models import (
    VM,
    Interface,
    KeySlot,
    News,
    Peer,
    Player,
    ServiceToken,
    TeamProfile,
    get_team_join_token,
)
from mainpage.network_lib import set_team_cloudhosting_status, set_team_testing_status


@admin.register(TeamProfile)
class TeamProfileAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "team_id",
        "captain",
        "irc_name",
        "website",
        "affiliation",
        "use_cloudhosting",
    ]
    actions = [
        "resend_confirmation_mail",
        "activate_team",
        "toggle_cloudhosting",
        "regenerate_invitation_link",
        "enable_test_mode",
        "disable_test_mode",
    ]

    def resend_confirmation_mail(self, request: HttpRequest, queryset) -> None:
        try:
            profiles: list[TeamProfile] = list(queryset)
            for team_profile in profiles:
                team_profile.send_confirmation_mail(request)
            messages.success(
                request, f"{len(profiles)} confirmation mails have been sent."
            )
        except:
            traceback.print_exc()
            messages.error(request, "Error sending confirmation mails")
            raise

    def activate_team(self, request: HttpRequest, queryset) -> None:
        try:
            count = 0
            profiles: list[TeamProfile] = list(queryset)
            for team_profile in profiles:
                if not team_profile.captain.is_active:
                    with transaction.atomic():
                        team_profile.confirm_team()
                        team_profile.captain.is_active = True
                        team_profile.captain.save()
                    count += 1
            messages.success(request, f"{count} teams have been activated.")
        except:
            traceback.print_exc()
            messages.error(request, "Error activating teams")
            raise

    def toggle_cloudhosting(self, request: HttpRequest, queryset) -> None:
        teams: list[TeamProfile] = list(queryset)
        msgs = []
        for team in teams:
            with transaction.atomic():
                msgs += set_team_cloudhosting_status(team, not team.use_cloudhosting)
        messages.success(request, "\n".join(msgs))

    def regenerate_invitation_link(self, request: HttpRequest, queryset) -> None:
        teams: list[TeamProfile] = list(queryset)
        for team in teams:
            team.join_token = get_team_join_token()
            team.save()
        messages.success(request, "Regenerated invitation link tokens")

    def enable_test_mode(self, request: HttpRequest, queryset) -> None:
        teams: list[TeamProfile] = list(queryset)
        msgs = []
        for team in teams:
            set_team_testing_status(team, True)
            msgs.append(f"Set team {team.name} as test team")

        messages.success(request, "\n".join(msgs))

    def disable_test_mode(self, request: HttpRequest, queryset) -> None:
        teams: list[TeamProfile] = list(queryset)
        msgs = []
        for team in teams:
            set_team_testing_status(team, False)
            msgs.append(f"Reset team {team.name} as test team")
        messages.success(request, "\n".join(msgs))

    resend_confirmation_mail.short_description = "Resend confirmation email"  # type: ignore
    activate_team.short_description = "Activate teams"  # type: ignore
    toggle_cloudhosting.short_description = "Toggle cloud-hosting status"  # type: ignore
    regenerate_invitation_link.short_description = (
        "Recreate join token / invitation link"  # type: ignore
    )
    enable_test_mode.short_description = "Network test mode: Enable"  # type: ignore
    disable_test_mode.short_description = "Network test mode: Disable"  # type: ignore


@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    pass


@admin.register(VM)
class VMAdmin(admin.ModelAdmin):
    pass


@admin.register(ServiceToken)
class ServiceTokenAdmin(admin.ModelAdmin):
    pass


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    change_form_template = "loginas/change_form.html"
    list_display = ("username", "email", "team", "role")
    list_filter = ("role", "team")
    search_fields = ("username", "email", "team__name")


@admin.register(KeySlot)
class KeySlotAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "owner", "public_key", "managed")


class PeerInline(admin.TabularInline):
    model = Peer
    formfield_overrides = {models.TextField: {"widget": TextInput}}


@admin.action(description="Set last modified to now")
def set_last_modified_now(modeladmin, request, queryset: QuerySet[Interface]):
    queryset.update(last_modified=timezone.now())


@admin.action(description="Set last synced to now")
def set_last_synced_now(modeladmin, request, queryset: QuerySet[Interface]):
    queryset.update(last_synced=timezone.now())


@admin.action(description="Reset last synced")
def reset_last_synced(modeladmin, request, queryset: QuerySet[Interface]):
    queryset.update(last_synced=None)


@admin.register(Interface)
class InterfaceAdmin(admin.ModelAdmin):
    list_display = ["id", "team", "public_key", "last_modified", "last_synced", "cidr"]
    inlines = [PeerInline]
    actions = [set_last_modified_now, set_last_synced_now, reset_last_synced]


@admin.register(Peer)
class PeerAdmin(admin.ModelAdmin):
    list_display = ("id", "enabled", "cidr", "type", "key_slot", "interface")
    list_filter = ("enabled", "type", "interface")
    search_fields = ("interface__team__name",)
