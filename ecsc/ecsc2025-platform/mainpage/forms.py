# from captcha.fields import CaptchaField, CaptchaTextInput
from django import forms
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from hcaptcha.fields import hCaptchaField

from mainpage.models import Player


class SignUpFormMixin(forms.Form):
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(),
    )
    password_confirm = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(),
    )
    email = forms.EmailField(required=True)

    def clean_username(self):
        username = self.cleaned_data["username"]
        username = username.strip() if username else username
        return username

    def clean_email(self):
        email = self.cleaned_data["email"]
        return email.strip()

    def clean_password(self):
        password = self.cleaned_data.get("password")
        validate_password(password)
        return password


class TeamSignupForm(forms.ModelForm, SignUpFormMixin):
    class Meta:
        model = Player
        fields = ("username", "email")
        widgets = {
            "email": forms.EmailInput(attrs={"placeholder": "Enter your email"}),
            "username": forms.TextInput(attrs={"placeholder": "Enter your username"}),
        }
        help_texts = {
            "email": "Only you and your teams technicians can see your email.",
            "username": "Used for login. Only you and your teams technicians will see your username.",
        }

    team_name = forms.CharField(
        label="Team name",
        max_length=128,
        required=True,
        min_length=1,
        widget=forms.TextInput(attrs={"placeholder": "Enter team name"}),
    )
    affiliation = forms.CharField(
        label="Affiliation",
        required=False,
        empty_value="",
        max_length=128,
        widget=forms.TextInput(
            attrs={"placeholder": "Enter your teams affiliation (optional)"}
        ),
    )
    if settings.USE_CAPTCHA:
        hcaptcha = hCaptchaField()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password") != cleaned.get("password_confirm"):
            raise ValidationError("Passwords don't match.")
        return cleaned


class PlayerSignupForm(forms.ModelForm, SignUpFormMixin):
    # Not validating the length of the token here, because form errors for
    #  hidden fields are - well - hidden...
    join_token = forms.CharField(widget=forms.HiddenInput())
    if settings.USE_CAPTCHA:
        hcaptcha = hCaptchaField()

    class Meta:
        model = Player
        fields = ("username", "email")
        widgets = {
            "email": forms.EmailInput(attrs={"placeholder": "Enter your email"}),
            "username": forms.TextInput(attrs={"placeholder": "Enter your username"}),
            "join_token": forms.HiddenInput(),
        }
        help_texts = {
            "email": "Only your team's captain and technicians will see your email.",
            "username": "Used for login. Only your team's captain and technicians will "
            "see your email.",
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password") != cleaned.get("password_confirm"):
            raise ValidationError("Passwords don't match.")
        return cleaned
