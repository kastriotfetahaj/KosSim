"""Views we use to manage things, outside of the django admin."""

import subprocess
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import markdown
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.mail import EmailMessage
from django.db.models import F
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode
from django_q.tasks import async_iter, result, result_group
from loginas.utils import login_as

from mainpage.models import EscapeHtml, News, Player, TeamProfile, User, VMStatusLog
from mainpage.network_lib import get_team_ip
from mainpage.utils import superuser_required
from mainpage.vmhosting import get_vms_for_admin_view


@login_required
@superuser_required
def news_edit(request: HttpRequest, id: int | None = None) -> HttpResponse:
    if id:
        news = News.objects.filter(id=id).get()
    else:
        news = None

    if request.method == "POST":
        text = request.POST["inputText"].strip()
        is_visible = request.POST.get("inputVisible", "") == "true"
        if not news:
            news = News(text=text)
        else:
            news.text = text
        news.html = markdown.markdown(news.text, extensions=[EscapeHtml()])
        news.html = news.html.replace(
            '<a href="http', '<a rel="noopener noreferrer" target="_blank" href="http'
        )
        news.title = request.POST["inputTitle"].strip()
        if not news.is_visible and is_visible:
            news.created_at = datetime.now()
        news.is_visible = is_visible
        if "preview" not in request.POST:
            news.save()
            messages.success(request, "News has been saved")
            return redirect(reverse("index"))
    return render(request, "news_edit.html", context={"news": news})


@login_required
@superuser_required
def team_list(request: HttpRequest) -> HttpResponse:
    teams: list[TeamProfile] = list(
        TeamProfile.objects.order_by(F("team_id").asc(nulls_last=True)).all()
    )
    if len(teams) <= 10:
        team_buckets = [teams]
    else:
        half = (len(teams) + 1) // 2
        team_buckets = [teams[:half], teams[half:]]
    count_cloud = 0
    count_cloud_active = 0
    count_active = 0
    for team in teams:
        if team.team_id:
            count_active += 1
            if team.use_cloudhosting:
                count_cloud_active += 1
        if team.use_cloudhosting:
            count_cloud += 1
    context = {
        "teams": teams,
        "team_buckets": team_buckets,
        "count_cloud": count_cloud,
        "count_active": count_active,
        "count_cloud_active": count_cloud_active,
        "count_inactive": len(teams) - count_active,
    }
    return render(request, "team_list.html", context=context)


@login_required
@superuser_required
def loginas_team(request: HttpRequest, team_pk: int) -> HttpResponse:
    captain = Player.objects.filter(
        team_id=team_pk, role=Player.RoleChoices.CAPTAIN
    ).get()
    user = User.objects.get(pk=captain.pk)  # login_as doesn't like our player model
    login_as(user, request)
    return redirect(reverse("team"))


@login_required
@superuser_required
def vm_list(request: HttpRequest) -> HttpResponse:
    vms_for_admin = get_vms_for_admin_view(request)
    vms = [
        (
            name,
            tmpl,
            vm,
            team,
            get_team_ip(cast(int, team.team_id), str(tmpl.ip_suffix)),
        )
        for name, tmpl, vm, team in vms_for_admin
    ]
    limit = int(request.GET.get("limit", 100))
    offset = int(request.GET.get("offset", 0))
    logs = VMStatusLog.objects.order_by("-created_at", "-id")[offset : offset + limit]
    return render(
        request,
        "vm_list.html",
        context={
            "vms": vms,
            "templates": settings.HOSTING_VM_TEMPLATES,
            "now": datetime.now().astimezone(),
            "logs": logs,
        },
    )


@login_required
@superuser_required
def scoreboard_upload(request: HttpRequest) -> HttpResponse:
    if request.method == "POST" and request.FILES["archive"]:
        try:
            directory: Path = settings.STATIC_ROOT or Path(settings.STATIC_DIR)
            with open("/tmp/scoreboard.7z", "wb") as f:
                f.write(request.FILES["archive"].read())  # type: ignore
            directory.mkdir(parents=True, exist_ok=True)
            subprocess.check_call(
                [
                    "7z",
                    "x",
                    "/tmp/scoreboard.7z",
                    "scoreboard",
                    "-o" + str(directory),
                    "-y",
                ]
            )
            # patch files
            indexfile = directory / "scoreboard" / "index.html"
            index = indexfile.read_text("utf-8")
            index = index.replace(
                '<base href="/">', '<base href="/static/scoreboard/">'
            )
            indexfile.write_text(index, "utf-8")
            for file in (directory / "scoreboard").iterdir():
                if file.name.startswith("main-") and file.name.endswith(".js"):
                    content = file.read_text("utf-8")
                    content = content.replace("/logos/", "logos/")
                    file.write_text(content, "utf-8")
            url = static("scoreboard/index.html" if settings.DEBUG else "scoreboard/")
            url = f"{request.scheme}://{request.get_host()}" + url
            messages.success(request, f"Scoreboard has been uploaded. Its url is {url}")
        except Exception as e:
            traceback.print_exc()
            messages.error(request, "Could not upload scoreboard: " + str(e))
    return render(request, "scoreboard_upload.html", context={})


@login_required
@superuser_required
def mail_test(request: HttpRequest) -> HttpResponse:
    try:
        if request.method == "POST":
            mail_subject = "Testmail"
            message = render_to_string(
                "email_confirmation.html",
                {
                    "uid": force_str(
                        urlsafe_base64_encode(force_bytes(request.user.pk))
                    ),
                    "token": "dummytoken",
                    "domain": request.META["HTTP_HOST"],
                    "user": request.user,
                },
            )
            email = request.user.email  # type: ignore
            EmailMessage(mail_subject, message, to=[email]).send()
            messages.success(request, "Email sent.")
        return render(request, "mail_test.html")
    except:  # noqa
        traceback.print_exc()
        resp = "<pre>" + traceback.format_exc() + "</pre>"
        return HttpResponse(resp, status=500)


def send_mail(msg: dict[str, Any]) -> tuple[list[str], str] | None:
    try:
        EmailMessage(**msg).send()
        return None
    except Exception as e:
        traceback.print_exc()
        return msg["to"], str(e)


@login_required
@superuser_required
def mail_all(request: HttpRequest):
    tasks = cache.get("mail_all_tasks", default=[])

    if request.method == "POST":
        subject = request.POST["inputSubject"].strip()
        text = request.POST["inputText"].strip()
        include_technicians = request.POST.get("inputTechnicians", "") == "true"
        if not subject or not text:
            messages.error(request, "Fill out subject and text!")
        else:
            roles = (
                (Player.RoleChoices.CAPTAIN, Player.RoleChoices.TECHNICIAN)
                if include_technicians
                else (Player.RoleChoices.CAPTAIN,)
            )
            players = (
                Player.objects.prefetch_related("team")
                .filter(role__in=roles, team__is_active=True)
                .all()
            )
            msgs = [
                dict(subject=subject, body=text, to=[player.email])
                for player in players
            ]
            task_id = async_iter(send_mail, msgs)
            messages.success(request, f"Scheduled {len(msgs)} emails")

            tasks = cache.get("mail_all_tasks", default=[])
            tasks = [
                {"task_id": task_id, "size": len(msgs), "ts": datetime.now()}
            ] + tasks
            cache.set("mail_all_tasks", tasks, timeout=7200)

    for task in tasks:
        task_id = task["task_id"]
        res = result(task_id)
        if res is None:
            res = result_group(
                task_id, failures=True, cached=True
            )  # intermediate results
        if res is None:
            res = []
        print(task_id, res)
        errors = [_ for _ in res if _ is not None]
        task["success"] = len(res) - len(errors)
        task["failed"] = len(errors)
        task["queued"] = task["size"] - len(res)
        task["failed_mails"] = ", ".join(
            ", ".join(error[0]) for error in errors if isinstance(error, tuple)
        )

    return render(
        request, "mail_all.html", context={"tasks": tasks, "now": datetime.now()}
    )
