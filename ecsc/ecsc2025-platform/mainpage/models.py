import functools
import hashlib
import hmac
from secrets import token_hex
from typing import TYPE_CHECKING

import markdown
from constance import config
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import Max
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode
from markdown.core import Markdown

from mainpage.tokens import account_activation_token

MAX_CIDR_LENGTH = len("255.255.255.255/255")
MAX_PUBK_LENGTH = 64  # "Empirically determined" + 20 bytes for good measure
MAX_PRIVK_LENGTH = 64  # "Empirically determined" + 20 bytes for good measure
TEAM_JOIN_TOKEN_LENGTH = 20


def get_team_join_token() -> str:
    return token_hex(TEAM_JOIN_TOKEN_LENGTH // 2)


if TYPE_CHECKING:
    from django.contrib.auth.models import User
else:
    User = get_user_model()


class TeamProfile(models.Model):
    name = models.CharField(
        max_length=150,
        null=False,
        blank=False,
        unique=True,
    )
    affiliation = models.TextField(null=True, blank=True)
    website = models.TextField(null=True, blank=True)
    irc_name = models.TextField(null=True, blank=True)
    team_id = models.IntegerField(  # a gameserver ID (once assigned)
        null=True,
        default=None,
        unique=True,
    )
    logo = models.TextField(blank=True, default="")
    ssh_keys = models.TextField(blank=True, default="")
    use_cloudhosting = models.BooleanField(null=False, default=False)
    join_token = models.CharField(
        max_length=TEAM_JOIN_TOKEN_LENGTH,
        null=True,
        blank=True,
        default=get_team_join_token,
    )
    is_active = models.BooleanField(default=False)

    @property
    def interface(self) -> "Interface":
        return Interface.objects.get(team=self)

    @property
    def captain(self) -> "Player":
        return Player.objects.get(team=self, role=Player.RoleChoices.CAPTAIN)

    @transaction.atomic
    def confirm_team(self):
        self.is_active = True
        if not self.team_id:
            max_id = TeamProfile.objects.aggregate(max_team_id=Max("team_id"))[
                "max_team_id"
            ]
            self.team_id = max_id + 1 if max_id else 2
            # Avoiding circular import
            from mainpage.network_lib import (
                prepare_team_network,
                set_team_cloudhosting_status,
            )

            prepare_team_network(self)
            set_team_cloudhosting_status(self, self.use_cloudhosting)
        self.save()

    def send_confirmation_mail(self, request):
        mail_subject = "Activate your captain account."
        user = self.captain
        message = render_to_string(
            "email_confirmation.html",
            {
                "uid": force_str(urlsafe_base64_encode(force_bytes(user.pk))),
                "token": account_activation_token.make_token(user),
                "domain": request.META["HTTP_HOST"],
                "user": user,
            },
        )
        EmailMessage(mail_subject, message, to=[user.email]).send()

    @property
    @functools.lru_cache()
    def ident_code(self):
        if not self.team_id:
            return ""
        long_code = int(
            hmac.new(
                (settings.SECRET_KEY + "_team_ident_code").encode(),
                str(self.team_id).encode(),
                "sha256",
            ).hexdigest(),
            16,
        )
        return str(long_code % 100000000)

    def __str__(self):
        return f"Team ({self.team_id}) {self.name}"


class Player(User):
    class Meta:
        verbose_name_plural = "Players"
        verbose_name = "Player"

    class RoleChoices(models.TextChoices):
        CAPTAIN = "CP", "Captain"
        TECHNICIAN = "TE", "Technician"
        PLAYER = "PL", "Player"

    team = models.ForeignKey(
        TeamProfile,
        null=False,
        on_delete=models.CASCADE,
    )
    role = models.CharField(
        max_length=2, choices=RoleChoices, default=RoleChoices.PLAYER
    )

    def __str__(self):
        return f"{self.role}: {self.username} <{self.email}>"

    @property
    def is_at_least_technician(self) -> bool:
        return self.role in (Player.RoleChoices.CAPTAIN, Player.RoleChoices.TECHNICIAN)

    @property
    def is_captain(self) -> bool:
        return self.role == Player.RoleChoices.CAPTAIN


@receiver(post_save, sender=Player)
def prepare_key_slot(sender, instance, created, **kwargs):
    if not config.VPN_DEFAULT_MANAGED and created:
        ks = KeySlot(
            name=f"{instance.username}'s personal key",
            owner=instance,
        )
        ks.save()


class News(models.Model):
    class Meta:
        verbose_name_plural = "News"

    title = models.TextField(blank=True, default="")
    text = models.TextField(blank=False)
    html = models.TextField(blank=False)
    is_visible = models.BooleanField(null=False, default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class VM(models.Model):
    kind = models.TextField(blank=False, null=False)
    team = models.ForeignKey(TeamProfile, on_delete=models.CASCADE, to_field="team_id")
    config = models.JSONField(null=False)
    status = models.JSONField(null=False)
    metadata = models.JSONField(null=False, default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["kind", "team_id"], name="kind_team_id")
        ]

    def __str__(self):
        return f"VM <{self.kind}, team {self.team_id}, {self.config['status']}/{self.status.get('status', 'MISSING')}>"


class VMStatusLog(models.Model):
    kind = models.TextField(blank=False, null=False)
    team = models.ForeignKey(TeamProfile, on_delete=models.CASCADE, to_field="team_id")
    field = models.TextField(blank=False, null=False)
    old_value = models.JSONField(null=True)
    new_value = models.JSONField(null=True)
    message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)


class EscapeHtml(markdown.Extension):
    def extendMarkdown(self, md: Markdown) -> None:
        md.preprocessors.deregister("html_block")
        md.inlinePatterns.deregister("html")


class ServiceToken(models.Model):
    name = models.TextField(blank=False, null=False)
    text = models.TextField(blank=False)
    html = models.TextField(blank=False)
    is_visible = models.BooleanField(null=False, default=False)
    secret = models.TextField(blank=False, null=False)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # TODO: This seems broken?
        self.token: str | None = None

    def set_token(self, team_id: int):
        self.token = hmac.HMAC(
            self.secret.encode(), str(team_id).encode(), hashlib.sha256
        ).hexdigest()[:32]

    def __str__(self) -> str:
        return f"ServiceToken <{self.id}, {self.name}, visible={self.is_visible}>"

    def save(self, *args, **kwargs):
        self.html = markdown.markdown(self.text, extensions=[EscapeHtml()])
        self.html = self.html.replace(
            '<a href="http', '<a rel="noopener noreferrer" target="_blank" href="http'
        )
        super().save(*args, **kwargs)


class KeySlot(models.Model):
    owner = models.ForeignKey(
        Player,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="keyslots",
    )
    name = models.CharField(max_length=200)
    public_key = models.CharField(
        max_length=MAX_PUBK_LENGTH, null=True, blank=True, unique=True
    )
    # private key is present for keys we generated ourselves (e.g., vulnbox key)
    private_key = models.CharField(
        max_length=MAX_PRIVK_LENGTH, null=True, blank=True, default=None
    )

    # Managed KeySlots can't be changed through the player api
    managed = models.BooleanField(default=False)

    def __str__(self):
        return f"KeySlot: '{self.name}' of {self.owner}"


@receiver(pre_delete, sender=KeySlot)
def delete_keyslot(sender, instance: KeySlot, **kwargs):
    for peer in Peer.objects.filter(key_slot=instance, enabled=True).all():
        peer.interface.last_modified = timezone.now()
        peer.interface.save()


class Interface(models.Model):
    team = models.ForeignKey(
        TeamProfile,
        null=False,
        blank=False,
        on_delete=models.CASCADE,
    )
    public_key = models.CharField(max_length=MAX_PUBK_LENGTH, null=True, blank=True)
    cidr = models.CharField(max_length=MAX_CIDR_LENGTH)
    auto_ip_assignment = models.BooleanField(default=True)
    # Managed interfaces can not be configured by users
    managed = models.BooleanField(default=False, null=False, blank=False)
    vpn_host = models.TextField(blank=True, null=True, default=None)
    vpn_port = models.PositiveIntegerField(
        blank=True,
        null=True,
        default=None,
        validators=[MinValueValidator(1), MaxValueValidator(65535)],
    )
    last_modified = models.DateTimeField(auto_now=True)
    last_synced = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        team_id = self.team.team_id
        team_id_str = f"{team_id:03}" if team_id is not None else "inactive team"
        if self.team.team_id is not None:
            return f"Interface of {team_id_str} <{self.team.name}> "
        else:
            return f"Interface of {self.team.team_id:03} <{self.team.name}> "


class Peer(models.Model):
    class TypeChoices(models.TextChoices):
        VULNBOX = "VB", "Vulnbox"
        EXPLOITER = "EX", "Exploiter"
        TESTING = "TE", "Testing"
        AUTOIP = "AI", "Auto IP"
        PREPARED_POOL = "PP", "Prepared Pool"

    interface = models.ForeignKey(
        Interface,
        related_name="peers",
        null=False,
        blank=False,
        on_delete=models.CASCADE,
    )
    key_slot = models.ForeignKey(
        KeySlot,
        related_name="peers",
        null=False,
        blank=False,
        on_delete=models.CASCADE,
    )
    comment = models.TextField(null=True, blank=True)
    enabled = models.BooleanField(default=True, null=False)
    cidr = models.CharField(max_length=MAX_CIDR_LENGTH)
    order = models.IntegerField(default=0)
    overrides = models.JSONField(null=True)
    vpn_host = models.TextField(blank=True, null=True, default=None)
    vpn_port = models.PositiveIntegerField(
        blank=True,
        null=True,
        default=None,
        validators=[MinValueValidator(1), MaxValueValidator(65535)],
    )

    @property
    def effective_vpn_host(self) -> str:
        return self.vpn_host or self.interface.vpn_host or config.VPN_HOST

    @property
    def effective_vpn_port(self):
        return (
            self.vpn_port
            or self.interface.vpn_port
            or config.VPN_BASE_PORT + self.interface.team.team_id
        )

    # Managed Peers can't be changed through the player api
    managed = models.BooleanField(default=False)

    # This is used to distinguish types of managed peers
    type = models.CharField(
        max_length=2, choices=TypeChoices, null=True, default=None, blank=True
    )

    def __str__(self):
        if not (team := self.key_slot.owner):
            team_id_str = "?Unowned keyslot?"
        elif not team.team_id:
            team_id_str = "inactive team"
        else:
            team_id_str = f"{team.team_id:03}"

        return f"Peer for {team_id_str} {self.cidr} {self.key_slot}"
