from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.urls import include, path

from mainpage import vmhosting
from mainpage.views import auth, endpoints, management, pages, team
from mainpage.views.api import player as player_api
from mainpage.views.api import router as router_api


def notfound(request: HttpRequest) -> HttpResponse:
    return HttpResponseNotFound("Not found")


def filter_subpath(x, cond: str):
    """Hacky way to filter unnecessary (potentially risky) stuff out of an imported module."""
    resolvers, _, _ = x
    resolvers.urlpatterns = [
        x for x in resolvers.urlpatterns if str(x.pattern).startswith(cond)
    ]
    return x


urlpatterns = [
    path("admin/login", notfound),
    path("admin/login/", notfound),
    path("admin/", include("loginas.urls")),
    path("admin/", admin.site.urls, name="admin"),
    path("accounts/", filter_subpath(include("allauth.urls"), "oidc/")),
    # Pages
    path("", pages.index, name="index"),
    path("rules", pages.rules, name="rules"),
    path("setup", pages.setup, name="setup"),
    path("teams", pages.teams, name="teams"),
    # User Management Endpoints
    path("signup", auth.signup, name="signup"),
    path("signup_player", auth.signup_player, name="signup_player"),
    path("signup_player/<str:token>", auth.signup_player, name="signup_player"),
    path("login", auth.login_view, name="login"),
    path("logout", auth.logout_view, name="logout"),
    path(r"activate/<str:uid_b64>/<str:token>/", auth.activate, name="activate"),
    path("password-reset", auth.MyPasswordResetView.as_view(), name="password_reset"),
    path(
        "password-reset/<uidb64>/<token>/",
        auth.MyPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path("debug", endpoints.debug, name="debug"),
    # Team Profile Endpoints
    path("team", team.team, name="team"),
    path("team/edit/info", team.team_change, name="change_team_info"),
    path("team/edit/icon", team.team_new_logo, name="change_logo"),
    path("team/edit/hosting", team.team_change_hosting, name="change_team_hosting"),
    path("team/export", endpoints.teams_export, name="teams_export"),
    path("team/edit/role", team.player_change_role, name="player_change_role"),
    path("team/edit/player_delete", team.player_delete, name="player_delete"),
    path(
        "vpn_config/<int:key_slot_id>",
        team.vpn_config_download,
        name="vpn_config_download",
    ),
    # VM Hosting Endpoints
    path("vms/config", vmhosting.vms_config, name="vms_config"),
    path("vms/status", vmhosting.vms_status, name="vms_status"),
    path("vms/sshkeys", vmhosting.edit_ssh_key, name="edit_ssh_key"),
    path("vms/action", vmhosting.vm_action, name="vm_action"),
    path("mail_test", management.mail_test, name="mail_test"),
    path("team_list", management.team_list, name="team_list"),
    path(
        "team_list/impersonate/<int:team_pk>",
        management.loginas_team,
        name="team_impersonate",
    ),
    path("vm_list", management.vm_list, name="vm_list"),
    path("vm_admin", vmhosting.vm_admin, name="vm_admin"),
    path("scoreboard_upload", management.scoreboard_upload, name="scoreboard_upload"),
    path("news/add", management.news_edit, name="news_add"),
    path("news/edit/<int:id>", management.news_edit, name="news_edit"),
    path("mail_teams", management.mail_all, name="mail_all"),
    path("api/player/interface", player_api.InterfaceView.as_view()),
    path("api/player/key_slots", player_api.ListKeySlotsView.as_view()),
    path("api/player/key_slots/<int:pk>", player_api.KeySlotView.as_view()),
    path("api/router/interface/<int:pk>", router_api.InterfaceDetailView.as_view()),
    path("api/router/interface/<int:pk>/sync", router_api.sync_interface),
    path("api/router/interfaces", router_api.InterfacesView.as_view()),
    path("api/router/testconfig", router_api.get_test_configs),
]

# In deployments, media files are served by caddy
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
