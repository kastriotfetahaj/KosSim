import traceback

from constance import config
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.views import PasswordResetConfirmView, PasswordResetView
from django.contrib.messages.views import SuccessMessageMixin
from django.db import transaction
from django.db.utils import IntegrityError
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.views.decorators.http import require_GET, require_http_methods
from django_q.tasks import Schedule, schedule
from loginas.utils import restore_original_login

from mainpage.forms import PlayerSignupForm, TeamSignupForm
from mainpage.models import Player, TeamProfile
from mainpage.tokens import account_activation_token


@require_http_methods(["GET", "POST"])
def login_view(request: HttpRequest) -> HttpResponse:
    ctx = {
        "oidc_name": settings.SOCIALACCOUNT_PROVIDERS["keycloak"]["APPS"][0][
            "provider_id"
        ]
        if "keycloak" in settings.SOCIALACCOUNT_PROVIDERS
        else None
    }
    if request.method == "GET":
        # Fixme: Next is not used on successfull logins!
        if request.GET.get("next", None):
            messages.error(request, "You need to be logged in to access this location!")
        return render(request, "login.html", context=ctx)
    elif request.method == "POST":
        user = request.POST.get("inputName", None)
        pwd = request.POST.get("inputPassword", None)
        if not (user and pwd):
            messages.error(request, "Username or Password is missing!")
            return render(request, "login.html", context=ctx)
        try:
            db_user = User.objects.get(username=user)
        except User.DoesNotExist:
            messages.error(request, "Username is incorrect!")
            return render(request, "login.html", context=ctx)
        if not db_user.is_active:
            messages.error(
                request, "Please activate your account first, check your mails!"
            )
            return render(request, "login.html", context=ctx)
        auth_user: User | None = authenticate(
            request=request, username=user, password=pwd
        )
        if auth_user and auth_user.is_active:
            login(request, auth_user)
            if auth_user.is_superuser:
                return redirect("team_list")
            else:
                return redirect(reverse("team"))
        else:
            messages.error(request, "Username/Password combination is incorrect!")
            return render(request, "login.html", context=ctx)
    else:
        return render(request, "login.html", context=ctx)


@require_GET
@login_required
def logout_view(request: HttpRequest) -> HttpResponse:
    restore_original_login(
        request
    )  # does normal logout if no "loginas" session is active
    if request.user and request.user.is_superuser:
        return redirect(reverse("team_list"))
    return redirect(reverse("index"))


@require_http_methods(("GET", "POST"))
def signup(request: HttpRequest) -> HttpResponse:
    if not config.ENABLE_SIGNUP:
        messages.error(request, "Registration is currently disabled")
        return redirect(reverse("index"))

    if request.method == "GET":
        return render(request, "signup.html", {"signupForm": TeamSignupForm()})
    else:
        form = TeamSignupForm(request.POST)
        if not form.is_valid():
            if settings.USE_CAPTCHA and form.has_error("hcaptcha"):
                messages.error(request, "Please complete captcha!")
                return render(request, "signup.html", {"signupForm": form}, status=251)
            return render(request, "signup.html", {"signupForm": form})

        team_name = form.cleaned_data["team_name"].strip()
        if TeamProfile.objects.filter(name__iexact=team_name).exists():
            form.add_error("team_name", "Team name already taken")
            messages.error(
                request,
                "Team name already taken. If you lost access to your account contact us.",
            )
            return render(request, "signup.html", {"signupForm": form})

        if User.objects.filter(email__iexact=form.cleaned_data["email"]).exists():
            form.add_error("email", "Email already taken")
            messages.error(
                request,
                "Email already taken. If you lost access to your account contact us.",
            )
            return render(request, "signup.html", {"signupForm": form})

        team = TeamProfile(
            name=team_name,
            affiliation=form.cleaned_data["affiliation"],
        )
        team.use_cloudhosting = (
            settings.HOSTING_ENABLED and settings.CLOUD_HOSTING_DEFAULT
        )

        captain = form.instance
        captain.active = False  # Captain needs to confirm email
        captain.set_password(form.cleaned_data["password"])
        captain.team = team
        captain.role = Player.RoleChoices.CAPTAIN

        try:
            team.save()
            captain.save()
        except IntegrityError:
            messages.error(request, "Team name or username already in use!")
            return render(request, "signup.html", {"signupForm": form})

        # Send Confirmation Mail
        try:
            team.send_confirmation_mail(request)
            messages.success(
                request,
                "Team Registered! Please Confirm your Email to finish the registration.",
            )
        except:
            traceback.print_exc()
            raise
        return redirect(reverse("index"))


def activate(request: HttpRequest, uid_b64: str, token: str) -> HttpResponse:
    if not config.ENABLE_ACTIVATION:
        messages.error(request, "Registration is closed.")
        return redirect(reverse("index"))
    try:
        uid = force_str(urlsafe_base64_decode(uid_b64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None
    if user is not None and account_activation_token.check_token(user, token):
        with transaction.atomic():
            user.is_active = True
            user.save()
            player = Player.objects.filter(id=user.id).first()
            if player and player.role == Player.RoleChoices.CAPTAIN:
                player.team.confirm_team()
        login(request, user)
        messages.success(request, "Thank you for confirming your email!")
        return redirect(reverse("team"))
    else:
        return HttpResponseBadRequest("Activation link is invalid!")


@require_http_methods(["GET", "POST"])
def signup_player(request: HttpRequest, token: str | None = None) -> HttpResponse:
    if request.user and request.user.is_authenticated:
        return redirect(reverse("team"))

    team: TeamProfile | None = None
    if request.method == "GET":
        try:
            team = TeamProfile.objects.get(join_token=token)
        except TeamProfile.DoesNotExist:
            messages.error(request, "Bad token provided")
            # return redirect("https://www.youtube.com/watch?v=v4tby3znOy8")
        form = PlayerSignupForm(initial=dict(join_token=token))
    else:
        form = PlayerSignupForm(request.POST)
        try:
            team = TeamProfile.objects.get(join_token=form.data.get("join_token"))
        except TeamProfile.DoesNotExist:
            messages.error(request, "Bad token!")
            return render(
                request, "signup_player.html", dict(player_signup=form), status=400
            )
        if form.is_valid():
            # Username uniqueness is validated in form, because model has unique
            if User.objects.filter(email__iexact=form.cleaned_data["email"]).exists():
                form.add_error("email", "Email already taken")
            else:
                player = form.instance
                player.team = team
                player.active = True  # Spare the players the email-verification
                player.set_password(form.cleaned_data["password"])
                player.role = Player.RoleChoices.PLAYER
                player.save()
                # TODO: Assign pooled keys?
                messages.success(request, "Registration successfull!")
                login(
                    request, player, backend="django.contrib.auth.backends.ModelBackend"
                )

                schedule(
                    "django.core.management.call_command",
                    "ensure_peers",
                    schedule_type=Schedule.ONCE,
                )
                return redirect(reverse("team"))

    return render(request, "signup_player.html", dict(player_signup=form, team=team))


class MyPasswordResetView(SuccessMessageMixin, PasswordResetView):
    template_name = "password_reset.html"
    email_template_name = "email_password_reset.html"
    subject_template_name = "email_password_reset_subject.txt"
    success_message = (
        "We've emailed you instructions for setting your password, "
        "if an account exists with the email you entered. You should receive them shortly."
        " If you don't receive an email, "
        "please make sure you've entered the address you registered with, and check your spam folder."
    )
    success_url = "/"


class MyPasswordResetConfirmView(SuccessMessageMixin, PasswordResetConfirmView):
    template_name = "password_reset_confirm.html"
    success_url = "/"
    success_message = "Passwort reset completed"
