from urllib.parse import urlencode

from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialLogin
from allauth.socialaccount.providers.openid_connect.provider import (
    OpenIDConnectProvider,
)
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest
from django.urls import reverse


class AdminSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Make all accounts from remote a super-admin."""

    def populate_user(
        self, request: HttpRequest, sociallogin: SocialLogin, data: dict
    ) -> AbstractUser:
        sociallogin.user.is_superuser = True
        sociallogin.user.is_staff = True
        return super().populate_user(request, sociallogin, data)


class KeycloakProvider(OpenIDConnectProvider):
    """Add group/role support."""

    id = "keycloak"
    name = "Keycloak"

    def get_login_url(self, request, **kwargs):
        url = reverse(
            "openid_connect_login", kwargs={"provider_id": self.app.provider_id}
        )
        if kwargs:
            url = url + "?" + urlencode(kwargs)
        return url

    def get_callback_url(self):
        return reverse(
            "openid_connect_callback",
            kwargs={"provider_id": self.app.provider_id},
        )

    def get_default_scope(self):
        return super().get_default_scope() + ["groups", "roles", "microprofile-jwt"]

    def extract_common_fields(self, data: dict):
        groups = data.get("groups", [])
        for grp in self.app.settings.get("required_groups", []):
            if grp not in groups:
                print(f"Authentication denied: group {grp} not in {groups}")
                raise PermissionDenied(f"Group {grp} not in {groups}")
        return super().extract_common_fields(data)


provider_classes = [KeycloakProvider]
